"""Release test for LowTube in real Firefox, against live YouTube.

Installs the built extension package into a throwaway Firefox profile and
checks, card by card, that it hides exactly the videos it should: every
toggle combination, threshold changes from the popup, in-app navigation,
search, the watch-page sidebar and channel grids, and that no shelf is left
showing a heading over an empty row. Optionally also upgrades
from a previous release and checks that saved settings survive.

usage:
  python tests/release_test.py web-ext-artifacts/lowtube_-_youtube_view_filter-1.1.zip
  python tests/release_test.py NEW.zip --upgrade-from PREVIOUS.zip
  python tests/release_test.py NEW.zip --headful        # watch it run

Exit code is 0 only if every check passed. Screenshots go to tests/output/.

Every check compares what the extension hid against an independent reading of
each card's metadata, so a pass means "hidden exactly when it should be".
Live YouTube content changes, so counts differ between runs; a check fails
only on a wrong hide/show decision or if a page shows no cards at all.
"""
import argparse, base64, json, os, re, shutil, socket, subprocess, sys, tempfile, time, traceback
from urllib.parse import unquote
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

EXT_ID = "me@numli.net"
EXT_UUID = "11111111-2222-3333-4444-555555555555"  # pinned so tests can open moz-extension:// pages
WIDGET_ID = "me_numli_net-browser-action"
PORT = int(os.environ.get("LOWTUBE_MARIONETTE_PORT", "2830"))
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
TOGGLES = ("filterVideos", "filterShorts", "filterLive")
ALL_ON = dict(filterVideos=True, filterShorts=True, filterLive=True)
CHECKBOXES = TOGGLES + ("showSubscribed",)  # every checkbox in the popup
DEFAULTS = {"minViews": "1000", **ALL_ON, "showSubscribed": False}

# Pages used by the tests. A big channel's grids stand in for the home feed
# (same ytd-rich-item-renderer cards), which is empty when logged out.
SEARCH_URL = "https://www.youtube.com/results?search_query=lofi+hip+hop"
SEARCH_URL_2 = "https://www.youtube.com/results?search_query=jazz+cafe+music"
WATCH_URL = "https://www.youtube.com/watch?v=jfKfPfyJRdk"
CHANNEL_URL = "https://www.youtube.com/@LofiGirl"
CHANNEL_MIN_VIEWS = 1_000_000  # Lofi Girl's counts range ~100K-100M

results = []  # (name, ok, detail)

def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}", flush=True)

# ---------------------------------------------------------------- browser ---
class Firefox:
    """Firefox with a throwaway profile, driven over Marionette.

    Firefox is started by us and geckodriver attaches to it. On macOS it is
    started through `open`, so it runs as itself: a Firefox spawned directly
    from a terminal or sandboxed tool can be denied access to its own
    Application Support folder by macOS privacy controls.
    """

    def __init__(self, headful=False):
        self.prof = tempfile.mkdtemp(prefix="lowtube-ff-")
        self.proc = None
        prefs = {
            "marionette.port": PORT,
            "intl.accept_languages": "en-US, en",
            "extensions.webextensions.uuids": json.dumps({EXT_ID: EXT_UUID}),
            "media.autoplay.default": 5,  # block autoplay
            "browser.shell.checkDefaultBrowser": False,
            "browser.startup.homepage_override.mstone": "ignore",
            "datareporting.policy.dataSubmissionEnabled": False,
            "toolkit.telemetry.reportingpolicy.firstRun": False,
            "browser.aboutwelcome.enabled": False,
        }
        with open(os.path.join(self.prof, "user.js"), "w") as f:
            for k, v in prefs.items():
                f.write(f"user_pref({json.dumps(k)}, {json.dumps(v)});\n")

        # Privileged access is needed to open the popup and read the console.
        # Firefox 159+ only grants it through the environment variable; older
        # versions also accept the -remote-allow-system-access flag.
        args = ["-no-remote", "-marionette", "-remote-allow-system-access", "-profile", self.prof, "about:blank"]
        if not headful:
            args.insert(0, "-headless")
        if sys.platform == "darwin":
            app = os.environ.get("FIREFOX_APP", "Firefox")
            subprocess.run(["open", "-n", "-g", "-a", app, "--env", "MOZ_REMOTE_ALLOW_SYSTEM_ACCESS=1",
                            "--args", *args], check=True)
        else:
            env = {**os.environ, "MOZ_REMOTE_ALLOW_SYSTEM_ACCESS": "1"}
            self.proc = subprocess.Popen([os.environ.get("FIREFOX_BIN", "firefox"), *args], env=env)

        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
                break
            except OSError:
                time.sleep(0.5)
        else:
            self.close()
            sys.exit(f"Firefox never opened Marionette port {PORT}")

        # Selenium Manager finds (or downloads) geckodriver.
        svc = Service(service_args=["--connect-existing", "--marionette-port", str(PORT)])
        self.d = webdriver.Firefox(service=svc, options=Options())
        self.d.set_window_size(1400, 1000)

    def close(self):
        try:
            if hasattr(self, "d"):
                self.d.quit()
        finally:
            if self.proc:
                self.proc.terminate()
            elif sys.platform != "win32":
                subprocess.run(["pkill", "-f", self.prof])
            time.sleep(1)
            shutil.rmtree(self.prof, ignore_errors=True)

    def chrome(self, script, *args, is_async=False):
        """Run privileged JS in the browser window (not in a page)."""
        self.d.set_context("chrome")
        try:
            run = self.d.execute_async_script if is_async else self.d.execute_script
            return run(script, *args)
        finally:
            self.d.set_context("content")

    def version(self):
        return self.chrome("return Services.appinfo.version")

    def install(self, path):
        self.d.install_addon(os.path.abspath(path), temporary=True)
        time.sleep(2)

# ------------------------------------------------------------------ popup ---
def open_popup_tab(ff):
    # WebDriver refuses moz-extension:// navigation, so open it from chrome context.
    d = ff.d
    main = d.current_window_handle
    before = set(d.window_handles)
    ff.chrome("""
      const tab = gBrowser.addTab(arguments[0], {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});
      gBrowser.selectedTab = tab;
    """, f"moz-extension://{EXT_UUID}/popup.html")
    time.sleep(1.5)
    d.switch_to.window([h for h in d.window_handles if h not in before][0])
    return main

def close_popup_tab(ff, main):
    ff.d.close()
    ff.d.switch_to.window(main)

def read_popup(ff):
    main = open_popup_tab(ff)
    vals = {"minViews": ff.d.find_element(By.ID, "minViews").get_attribute("value")}
    for key in CHECKBOXES:
        els = ff.d.find_elements(By.ID, key)
        vals[key] = els[0].is_selected() if els else None
    close_popup_tab(ff, main)
    return vals

def save_popup(ff, min_views, **toggles):
    """Change settings through the popup UI and click Save."""
    main = open_popup_tab(ff)
    inp = ff.d.find_element(By.ID, "minViews")
    inp.clear()
    inp.send_keys(str(min_views))
    for key, want in toggles.items():
        box = ff.d.find_element(By.ID, key)
        if box.is_selected() != want:
            box.click()
    ff.d.find_element(By.ID, "saveButton").click()
    time.sleep(1)
    close_popup_tab(ff, main)
    time.sleep(1)  # storage.onChanged -> re-filter

def set_subscriptions(ff, channels):
    """Replace the extension's saved subscription list: [[channel id, "/@handle"], ...].

    Logged out there is no list to read from YouTube, so tests supply one."""
    main = open_popup_tab(ff)
    ff.d.execute_async_script("""
      const done = arguments[arguments.length - 1];
      browser.storage.local.set({ subscriptions: { channels: arguments[0], at: Date.now() } }).then(() => done(true), e => done(String(e)));
    """, channels)
    close_popup_tab(ff, main)
    time.sleep(1)

# Opens the real toolbar popup from Firefox's Extensions (puzzle-piece) menu,
# as a user would, and snapshots it.
REAL_POPUP_JS = r"""
  const done = arguments[arguments.length - 1];
  (async () => {
    if (!CustomizableUI.getWidget(arguments[0])) return done({ error: 'widget not registered' });
    await gUnifiedExtensions.togglePanel();
    await new Promise(r => setTimeout(r, 800));
    const item = document.getElementById(arguments[0]);
    if (!item) return done({ error: 'button missing from Extensions menu' });
    (item.querySelector('.unified-extensions-item-action-button') || item).click();
    let b;
    for (let i = 0; i < 40; i++) {
      await new Promise(r => setTimeout(r, 250));
      b = document.querySelector('browser.webextension-popup-browser, browser[webextension-view-type="popup"]');
      if (b && b.currentURI?.spec.endsWith('/popup.html') && b.clientHeight > 50) break;
    }
    if (!b) return done({ error: 'popup did not open' });
    await new Promise(r => setTimeout(r, 1000));  // let storage values load
    const bmp = await b.browsingContext.currentWindowGlobal.drawSnapshot(null, 1, 'white');
    const c = document.createElementNS('http://www.w3.org/1999/xhtml', 'canvas');
    c.width = bmp.width; c.height = bmp.height;
    c.getContext('2d').drawImage(bmp, 0, 0);
    const res = { url: b.currentURI.spec, width: b.clientWidth, height: b.clientHeight, png: c.toDataURL('image/png') };
    b.closest('panel')?.hidePopup();
    gUnifiedExtensions.panel.hidePopup?.();
    done(res);
  })().catch(e => done({ error: String(e) }));
"""

def real_popup_snapshot(ff, path):
    res = ff.chrome(REAL_POPUP_JS, WIDGET_ID, is_async=True)
    if res.get("png"):
        with open(path, "wb") as f:
            f.write(base64.b64decode(res.pop("png").split(",", 1)[1]))
    return res

# ---------------------------------------------------------------- youtube ---
CARD_SEL = ("ytd-video-renderer, ytd-rich-item-renderer, ytd-compact-video-renderer, ytd-grid-video-renderer, "
            "yt-lockup-view-model, ytm-shorts-lockup-view-model, ytm-shorts-lockup-view-model-v2")

def reject_consent(ff):
    """Decline YouTube's non-essential cookies (EU consent page)."""
    ff.d.get("https://www.youtube.com/?hl=en&gl=US")
    time.sleep(3)
    if "consent." in ff.d.current_url:
        for b in ff.d.find_elements(By.CSS_SELECTOR, "button"):
            if (b.get_attribute("aria-label") or b.text or "").strip().lower().startswith("reject all"):
                b.click()
                break
        time.sleep(3)

def dismiss_inpage_consent(ff):
    ff.d.execute_script("""
      const b = [...document.querySelectorAll('button')]
        .find(b => /^reject all/i.test((b.getAttribute('aria-label') || b.textContent || '').trim()));
      if (b) b.click();
    """)

def wait_for_cards(ff, n=5, timeout=15):
    for _ in range(timeout * 2):
        if ff.d.execute_script(f"return document.querySelectorAll({json.dumps(CARD_SEL)}).length") >= n:
            return True
        time.sleep(0.5)
    return False

def load(ff, url, scrolls=2):
    ff.d.get(url)
    wait_for_cards(ff)
    time.sleep(2)
    dismiss_inpage_consent(ff)
    for _ in range(scrolls):  # trigger lazy-loaded cards
        ff.d.execute_script("window.scrollBy(0, 2500)")
        time.sleep(2)
    time.sleep(1)

def click_first_visible(ff, selector):
    ff.d.execute_script("""[...document.querySelectorAll(arguments[0])].find(a => a.offsetParent !== null).click();""", selector)

def extension_console_errors(ff):
    """Errors and warnings logged by the extension's scripts."""
    return ff.chrome("""
      const out = [];
      for (const m of Services.console.getMessageArray() || []) {
        if (!(m instanceof Ci.nsIScriptError)) continue;
        const src = m.sourceName || '';
        if (src.includes(arguments[0]) || /\\/(content|popup|background)\\.js$/.test(src)) {
          out.push({ error: !(m.flags & Ci.nsIScriptError.warningFlag), src: src.split('/').pop(), line: m.lineNumber, text: m.errorMessage });
        }
      }
      return out;
    """, EXT_UUID)

# ------------------------------------------------------------- the oracle ---
REPORT_JS = r"""
const [sel, withChannels] = arguments;
// Only judge cards on the active page: YouTube keeps previous pages (e.g. search
// results after clicking into a video) in the DOM, hidden.
const PAGE = 'ytd-page-manager > *';
const shown = e => getComputedStyle(e).display !== 'none';
// 'lowtube' if the extension's attribute hides the card, 'page' if YouTube
// itself hides it (e.g. the clip inside a collapsed announcement banner).
const hiddenBy = el => {
  for (let e = el; e && !e.matches(PAGE); e = e.parentElement) {
    if (!shown(e)) return e.hasAttribute('data-lowtube-hidden') ? 'lowtube' : 'page';
  }
  return null;
};
// Which channel a card is from, read from YouTube's data by string search
// (independently of how content.js walks it), plus the channel link if the
// card shows one, to cross-check the two.
const CH_RE = /"browseId":"(UC[\w-]{22})"(?:,"params":"[^"]*")?(?:,"canonicalBaseUrl":"\/(@[^"\/]+))?/;
const lower = h => { try { return decodeURIComponent(h).toLowerCase(); } catch (e) { return h.toLowerCase(); } };
const chIn = s => { const m = s && s.match(CH_RE); return m ? { id: m[1], handle: m[2] ? lower(m[2]) : null } : null; };
const json = o => { try { return JSON.stringify(o); } catch (e) { return null; } };
const videoIdOf = el => {
  for (const a of el.querySelectorAll('a[href]')) {
    const m = a.getAttribute('href').match(/[?&]v=([\w-]{11})|^\/shorts\/([\w-]{11})/);
    if (m) return m[1] || m[2];
  }
  return null;
};
const channelOf = el => {
  let ch = null;
  for (const host of [el, el.closest('ytd-rich-item-renderer'), el.querySelector('ytd-video-renderer')]) {
    if (host && host.data && (ch = chIn(json(host.data)))) break;
  }
  const vid = videoIdOf(el);
  for (let p = el.parentElement; !ch && vid && p && !p.matches(PAGE); p = p.parentElement) {
    const list = p.data && (p.data.contents || p.data.items);
    if (!Array.isArray(list)) continue;
    for (const item of list) {
      const s = json(item);
      if (s && s.includes('"' + vid + '"') && (ch = chIn(s))) break;
    }
  }
  const a = el.querySelector('a[href^="/@"]');
  const link = a && (a.getAttribute('href').match(/^\/(@[^\/?#]+)/) || [])[1];
  const linkHandle = link ? lower(link) : null;
  const conflict = !!(ch && ch.handle && linkHandle && ch.handle !== linkHandle);
  if (!ch && linkHandle) ch = { id: null, handle: linkHandle };
  return { chId: ch ? ch.id : null, chHandle: ch ? (ch.handle || linkHandle) : null, chConflict: conflict };
};
const out = [];
for (const el of document.querySelectorAll(sel)) {
  if (el.parentElement && el.parentElement.closest(sel)) continue;  // count outermost card only
  if (el.closest('ytd-playlist-panel-renderer')) continue;
  const page = el.closest(PAGE);
  if (page && (!shown(page) || page.hasAttribute('hidden'))) continue;
  const by = hiddenBy(el);
  if (by === 'page') continue;  // not visible regardless of the extension
  const title = (el.querySelector('#video-title, h3, [class*="Title"]')?.textContent || '').trim();
  const meta = [...el.querySelectorAll('#metadata-line span, yt-content-metadata-view-model span[role="text"], [class*="Subhead"] span[role="text"]')]
      .map(s => s.textContent.trim()).filter(Boolean);
  const short = /^YTM-SHORTS/.test(el.tagName) || !!el.querySelector('ytm-shorts-lockup-view-model, a[href^="/shorts/"]');
  const ad = !!el.querySelector('ytd-ad-slot-renderer, ytd-in-feed-ad-layout-renderer');
  // Shorts' data never names the channel, so the extension can't use it either.
  const channel = withChannels && !short ? channelOf(el) : { chId: null, chHandle: null, chConflict: false };
  out.push({ hidden: by === 'lowtube', title: Array.from(title).slice(0, 45).join(''), meta, short, ad, ...channel });
}
return out;
"""

# Shelves whose heading is still showing although the extension hid every card
# in them. Mirrors SHELF_SELECTOR in content.js.
SHELF_SEL = "grid-shelf-view-model, ytd-reel-shelf-renderer, ytd-rich-shelf-renderer, ytd-shelf-renderer"
SHELVES_JS = r"""
const [shelfSel, cardSel] = arguments;
const PAGE = 'ytd-page-manager > *';
const shown = e => getComputedStyle(e).display !== 'none';
const visible = el => { for (let e = el; e && !e.matches(PAGE); e = e.parentElement) { if (!shown(e)) return false; } return true; };
const res = { empty: [], hidden: 0 };
for (const s of document.querySelectorAll(shelfSel)) {
  const page = s.closest(PAGE);
  if (page && (!shown(page) || page.hasAttribute('hidden'))) continue;
  const cards = [...s.querySelectorAll(cardSel)];
  if (!cards.length) continue;
  const allOurs = cards.every(c => !visible(c) && c.closest('[data-lowtube-hidden]'));
  if (!visible(s)) { if (s.closest('[data-lowtube-hidden]')) res.hidden++; continue; }
  if (allOurs) res.empty.push((s.querySelector('h2, #title, [class*="Title"]')?.textContent || s.tagName).trim().slice(0, 30));
}
return res;
"""

CNT = re.compile(r"^([\d.,]+)\s*([KMB])?(?: views?| watching)?$", re.I)
MULT = {"k": 1e3, "m": 1e6, "b": 1e9}

def oracle_views(meta):
    for seg in meta:
        if seg.lower() == "no views":
            return 0
        m = CNT.match(seg)
        if m:
            return float(m.group(1).replace(",", "")) * MULT.get((m.group(2) or "").lower(), 1)
    return None

def page_channel(url):
    """(channel id, "@handle") from a channel page URL, else (None, None)."""
    m = re.match(r"https://www\.youtube\.com/(?:channel/(UC[\w-]{22})|(@[^/?#]+))", url)
    if not m:
        return None, None
    return m.group(1), unquote(m.group(2)).lower() if m.group(2) else None

def is_subscribed(it, subs, url):
    ids, handles = subs
    ch_id, handle = (it["chId"], it["chHandle"]) if (it["chId"] or it["chHandle"]) else page_channel(url)
    return (ch_id is not None and ch_id in ids) or (handle is not None and handle in handles)

def check_page(ff, name, min_views, cfg, subs=None, expect_kept=False):
    """subs: (channel ids, "@handles") given to the extension, when cfg has showSubscribed.
    expect_kept: fail unless at least one card is shown only because of its channel."""
    with_subs = bool(cfg.get("showSubscribed")) and subs is not None
    items = ff.d.execute_script(REPORT_JS, CARD_SEL, with_subs)
    url = ff.d.current_url
    stats, bad, kept = {}, [], 0
    for it in items:
        if it["ad"]:
            continue
        kind = "short" if it["short"] else "live" if any("watching" in s for s in it["meta"]) else "video"
        v = oracle_views(it["meta"])
        key = {"video": "filterVideos", "short": "filterShorts", "live": "filterLive"}[kind]
        want = min_views > 0 and v is not None and v < min_views and cfg[key]
        if want and with_subs and is_subscribed(it, subs, url):
            want = False
            kept += 1
        if it["chConflict"]:
            bad.append(f"channel in data ≠ channel link for {it['title']!r}")
        st = stats.setdefault(kind, [0, 0])
        st[0] += 1
        st[1] += it["hidden"]
        if want != it["hidden"]:
            bad.append(f"{kind} {' • '.join(it['meta'])!r} {it['title']!r} is {'hidden' if it['hidden'] else 'shown'}")
    shelves = ff.d.execute_script(SHELVES_JS, SHELF_SEL, CARD_SEL)
    bad += [f"shelf {t!r} shows a heading but all its cards are hidden" for t in shelves["empty"]]
    if expect_kept and not kept:
        bad.append("no card was kept for its subscribed channel")
    on = ",".join(k[6:].lower() for k in TOGGLES if cfg[k]) or "none"
    if cfg.get("showSubscribed"):
        on += ", subscribed shown"
    summary = "  ".join(f"{k}: {h}/{n} hidden" for k, (n, h) in sorted(stats.items())) or "no cards found"
    if with_subs:
        summary += f"  kept for subscription: {kept}"
    if shelves["hidden"]:
        summary += f"  shelves: {shelves['hidden']} hidden"
    ok = not bad and sum(n for n, _ in stats.values()) > 0
    record(f"{name} [min={min_views}, filter={on}]", ok, summary + ("" if not bad else "  MISMATCH: " + " | ".join(bad[:5])))

def check_subscriptions(ff, name, min_views):
    """Pretend to follow every other channel whose videos are being hidden;
    then exactly those channels' videos must come back, the rest stay hidden."""
    save_popup(ff, min_views, **ALL_ON, showSubscribed=False)
    hidden = {}
    for it in ff.d.execute_script(REPORT_JS, CARD_SEL, True):
        if it["hidden"] and not it["ad"] and it["chId"]:
            hidden.setdefault(it["chId"], it["chHandle"])
    picked = sorted(hidden.items())[::2]
    set_subscriptions(ff, [[i, "/" + h if h else None] for i, h in picked])
    save_popup(ff, min_views, **ALL_ON, showSubscribed=True)
    subs = ({i for i, _ in picked}, {h for _, h in picked if h})
    check_page(ff, f"{name}, {len(picked)} of {len(hidden)} channels subscribed", min_views,
               {**ALL_ON, "showSubscribed": True}, subs, expect_kept=True)
    set_subscriptions(ff, [])
    save_popup(ff, min_views, **ALL_ON, showSubscribed=False)

# ------------------------------------------------------------------ suites ---
TOGGLE_CONFIGS = [
    ALL_ON,
    dict(filterVideos=False, filterShorts=True, filterLive=True),
    dict(filterVideos=True, filterShorts=False, filterLive=True),
    dict(filterVideos=True, filterShorts=True, filterLive=False),
    dict(filterVideos=False, filterShorts=False, filterLive=False),
]

def fresh_install_suite(pkg, headful):
    ff = Firefox(headful)
    try:
        print(f"\n== Fresh install: Firefox {ff.version()}, {os.path.basename(pkg)}", flush=True)
        ff.install(pkg)

        pop = real_popup_snapshot(ff, os.path.join(OUT_DIR, "popup.png"))
        record("real toolbar popup opens from Extensions menu", "error" not in pop and pop.get("height", 0) > 100, json.dumps(pop))
        vals = read_popup(ff)
        record("fresh install defaults in popup", vals == DEFAULTS, json.dumps(vals))

        reject_consent(ff)

        # Search: videos, a Shorts shelf and live streams together.
        load(ff, SEARCH_URL)
        for cfg in TOGGLE_CONFIGS:
            save_popup(ff, 1000, **cfg)
            check_page(ff, "search", 1000, cfg)
        save_popup(ff, 0, **ALL_ON)
        check_page(ff, "search", 0, ALL_ON)
        check_subscriptions(ff, "search", 1_000_000)

        # Watch-page sidebar: every toggle combination, then threshold changes.
        load(ff, WATCH_URL, scrolls=1)
        for cfg in TOGGLE_CONFIGS:
            save_popup(ff, 1000, **cfg)
            check_page(ff, "watch sidebar", 1000, cfg)
        for n in (0, 100000, 1000):
            save_popup(ff, n, **ALL_ON)
            check_page(ff, "watch sidebar", n, ALL_ON)
        ff.d.save_screenshot(os.path.join(OUT_DIR, "watch.png"))
        check_subscriptions(ff, "watch sidebar", 100_000)
        save_popup(ff, 1000, **ALL_ON)

        # In-app navigation, watch -> watch: YouTube recycles the card elements.
        title = ff.d.title
        click_first_visible(ff, '#secondary yt-lockup-view-model a[href^="/watch"], #related yt-lockup-view-model a[href^="/watch"]')
        for _ in range(30):
            time.sleep(0.5)
            if ff.d.title != title:
                break
        time.sleep(6)
        check_page(ff, "watch -> watch in-app navigation", 1000, ALL_ON)

        # In-app navigation, search -> watch: the content script was injected only once.
        load(ff, SEARCH_URL_2, scrolls=0)
        click_first_visible(ff, 'ytd-video-renderer a#thumbnail[href^="/watch"]')
        for _ in range(30):
            time.sleep(0.5)
            if "/watch" in ff.d.current_url:
                break
        wait_for_cards(ff, 10)
        time.sleep(5)
        check_page(ff, "search -> watch in-app navigation", 1000, ALL_ON)

        # Channel grids (same card wrapper as the home feed).
        save_popup(ff, CHANNEL_MIN_VIEWS, **ALL_ON)
        for tab in ("videos", "shorts", "streams"):
            load(ff, f"{CHANNEL_URL}/{tab}")
            check_page(ff, f"channel /{tab} grid", CHANNEL_MIN_VIEWS, ALL_ON)

        # A subscribed channel's own pages: the cards there don't name the
        # channel (Shorts never do), so the extension goes by the page URL.
        ch_id = ff.d.execute_script(
            "return (document.querySelector('link[rel=\"canonical\"]')?.href.match(/channel\\/(UC[\\w-]{22})/) || [])[1] || null")
        set_subscriptions(ff, [[ch_id, "/" + CHANNEL_URL.rsplit("/", 1)[1]]])
        save_popup(ff, CHANNEL_MIN_VIEWS, **ALL_ON, showSubscribed=True)
        subs = ({ch_id} - {None}, {CHANNEL_URL.rsplit("/", 1)[1].lower()})
        for tab in ("videos", "shorts"):
            load(ff, f"{CHANNEL_URL}/{tab}")
            check_page(ff, f"subscribed channel's /{tab} grid", CHANNEL_MIN_VIEWS,
                       {**ALL_ON, "showSubscribed": True}, subs, expect_kept=True)
        set_subscriptions(ff, [])
        save_popup(ff, 1000, **ALL_ON, showSubscribed=False)

        msgs = extension_console_errors(ff)
        record("no extension errors in Firefox console", not [m for m in msgs if m["error"]],
               json.dumps(msgs[:5]) if msgs else "console clean")
    finally:
        ff.close()

def upgrade_suite(old_pkg, pkg, headful):
    ff = Firefox(headful)
    try:
        print(f"\n== Upgrade: Firefox {ff.version()}, {os.path.basename(old_pkg)} -> {os.path.basename(pkg)}", flush=True)
        ff.install(old_pkg)
        # Save 0 ("filter nothing"): v1.0's background script reset that to
        # 1000 on every update. Uses only the minViews field, which every
        # version's popup has.
        main = open_popup_tab(ff)
        inp = ff.d.find_element(By.ID, "minViews")
        inp.clear()
        inp.send_keys("0")
        ff.d.find_element(By.ID, "saveButton").click()
        time.sleep(1)
        close_popup_tab(ff, main)
        old_errors = {(m["src"], m["line"], m["text"]) for m in extension_console_errors(ff)}

        ff.install(pkg)
        vals = read_popup(ff)
        record("upgrade keeps saved minViews=0, new settings at defaults", vals == {**DEFAULTS, "minViews": "0"}, json.dumps(vals))

        reject_consent(ff)
        load(ff, SEARCH_URL)
        check_page(ff, "search after upgrade", 0, ALL_ON)

        save_popup(ff, 5000, **ALL_ON)
        vals = read_popup(ff)
        record("settings saved after upgrade persist", vals == {**DEFAULTS, "minViews": "5000"}, json.dumps(vals))
        check_page(ff, "search after upgrade", 5000, ALL_ON)

        new_errors = [m for m in extension_console_errors(ff)
                      if m["error"] and (m["src"], m["line"], m["text"]) not in old_errors]
        record("no extension errors after upgrade", not new_errors, json.dumps(new_errors[:5]) if new_errors else "console clean")
    finally:
        ff.close()

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("package", help="built extension (.zip/.xpi) or source directory to test")
    ap.add_argument("--upgrade-from", metavar="OLD", help="previous release (.zip/.xpi or directory) to upgrade from")
    ap.add_argument("--headful", action="store_true", help="show the Firefox window")
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)

    suites = [("fresh install", lambda: fresh_install_suite(args.package, args.headful))]
    if args.upgrade_from:
        suites.append(("upgrade", lambda: upgrade_suite(args.upgrade_from, args.package, args.headful)))
    for name, run in suites:
        try:
            run()
        except Exception:
            traceback.print_exc()
            record(f"{name} suite ran to completion", False, "exception, see traceback above")

    passed = sum(ok for _, ok, _ in results)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    for name, ok, detail in results:
        if not ok:
            print(f"FAIL {name}\n     {detail}")
    print(f"screenshots: {OUT_DIR}")
    sys.exit(0 if results and passed == len(results) else 1)

if __name__ == "__main__":
    main()
