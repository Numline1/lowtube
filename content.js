'use strict';

const DEFAULT_SETTINGS = {
  minViews: 1000,
  filterVideos: true,
  filterShorts: true,
  filterLive: true,
  showSubscribed: false,
};
const HIDDEN_ATTR = 'data-lowtube-hidden';

// Video cards we know how to read, across YouTube's legacy Polymer renderers
// and the newer "view model" components.
const CARD_SELECTOR = [
  'ytd-rich-item-renderer',          // home / channel grid wrapper
  'ytd-video-renderer',              // search results
  'ytd-compact-video-renderer',      // legacy watch-page sidebar
  'ytd-grid-video-renderer',         // legacy grids
  'yt-lockup-view-model',            // watch-page sidebar, new home grid
  'ytm-shorts-lockup-view-model',    // Shorts shelves
].join(',');

// Shelves: a heading over a row of cards. When every card in a shelf is
// hidden, the shelf is hidden too, so its heading isn't left over an empty row.
const SHELF_SELECTOR = [
  'grid-shelf-view-model',           // search: Shorts grid
  'ytd-reel-shelf-renderer',         // legacy Shorts shelf
  'ytd-rich-shelf-renderer',         // home: Shorts shelf
  'ytd-shelf-renderer',              // search / channel: titled video shelves
].join(',');

// Lists the user put together themselves; never filter these.
const SKIP_CONTAINERS = 'ytd-playlist-panel-renderer, ytd-playlist-video-list-renderer';

// Where a card's metadata text lives in each layout.
const METADATA_TEXT_SELECTOR = [
  '#metadata-line span',                          // legacy: "1.2M views", "3y ago"
  'yt-content-metadata-view-model span[role="text"]', // lockup: "Channel", "1.2M", "3y ago"
  '[class*="Subhead"] span[role="text"]',        // Shorts: "1.2M views"
].join(',');

// A Short in any layout: Shorts lockups, or a regular card linking to /shorts/.
const SHORTS_SELECTOR = [
  'ytm-shorts-lockup-view-model',
  'a#thumbnail[href^="/shorts/"]',
  'a#video-title[href^="/shorts/"]',
  'yt-lockup-view-model a[href^="/shorts/"]',
].join(',');

// "LIVE" thumbnail badge, used as a language-independent live signal.
const LIVE_BADGE_SELECTOR = [
  '.ytBadgeShapeThumbnailLive',
  '.yt-badge-shape--thumbnail-live',
  '.badge-style-type-live-now-alpha',
  'ytd-thumbnail-overlay-time-status-renderer[overlay-style="LIVE"]',
].join(',');

const VIEW_WORD_RE = /\b(views?|watching)\b/i;
const WATCHING_RE = /\bwatching\b/i;
const MULTIPLIERS = { k: 1e3, thousand: 1e3, m: 1e6, million: 1e6, b: 1e9, billion: 1e9 };
// "92", "1,234 views", "1.5K", "15K watching", "1.5 thousand views"
const COUNT_RE = /^(\d[\d,]*(?:\.\d+)?)\s*(k|m|b|thousand|million|billion)?(?:\s+(?:views?|watching))?$/;

// Filtering stays off (minViews 0) until the saved settings load.
let settings = { ...DEFAULT_SETTINGS, minViews: 0 };

// Returns the number of views, or null when the text isn't a view count.
// Unknown formats (other locales, "Premieres ...", playlists) return null so
// they are left visible rather than hidden by mistake.
function parseViewCount(text) {
  if (!text) return null;
  const t = text.replace(/\s+/g, ' ').trim().toLowerCase();
  if (t === 'no views') return 0;
  const m = t.match(COUNT_RE);
  if (!m) return null;
  const n = parseFloat(m[1].replace(/,/g, ''));
  return Math.round(n * (MULTIPLIERS[m[2]] || 1));
}

// Returns { views, watching }: the count (or null if unreadable) and whether
// it is a live "N watching" count rather than total views.
function readViewCount(card) {
  const spans = card.querySelectorAll(METADATA_TEXT_SELECTOR);

  // Prefer a span explicitly labelled as views / watching. The lockup layout
  // shows a bare "1.5K" but labels it "1.5 thousand views" for screen readers.
  for (const span of spans) {
    const label = span.getAttribute('aria-label') || '';
    const text = span.textContent;
    if (VIEW_WORD_RE.test(label) || VIEW_WORD_RE.test(text)) {
      const views = parseViewCount(text) ?? parseViewCount(label);
      if (views !== null) return { views, watching: WATCHING_RE.test(label + ' ' + text) };
    }
  }

  // Legacy layout shows "58M" with no label; it is always the first item of
  // #metadata-line (the channel name lives elsewhere).
  const first = card.querySelector('#metadata-line span');
  const text = first ? first.textContent : '';
  return { views: parseViewCount(text), watching: WATCHING_RE.test(text) };
}

function cardKind(card, watching) {
  if (card.matches(SHORTS_SELECTOR) || card.querySelector(SHORTS_SELECTOR)) return 'short';
  if (watching || card.querySelector(LIVE_BADGE_SELECTOR)) return 'live';
  return 'video';
}

function isKindFiltered(kind) {
  if (kind === 'short') return settings.filterShorts;
  if (kind === 'live') return settings.filterLive;
  return settings.filterVideos;
}

// Hide the outermost wrapper so grids and shelves don't keep an empty slot.
function hideTarget(card) {
  return card.closest('ytd-rich-item-renderer') ||
         card.closest('.ytGridShelfViewModelGridShelfItem') || // Shorts shelf cell
         card.closest('ytm-shorts-lockup-view-model-v2') ||
         card;
}

// The home feed wraps each shelf in a grid section; hide that so no gap stays.
function shelfHideTarget(shelf) {
  return shelf.closest('ytd-rich-section-renderer') || shelf;
}

function setHidden(el, hidden) {
  if (hidden === el.hasAttribute(HIDDEN_ATTR)) return;
  if (hidden) el.setAttribute(HIDDEN_ATTR, '');
  else el.removeAttribute(HIDDEN_ATTR);
}

// ------------------------------------------------- subscribed channels ---
// With "Always show channels I'm subscribed to" on, a low-view card stays
// visible when it comes from a subscribed channel. YouTube doesn't always put
// the channel on the card itself, so this also reads the data YouTube keeps
// on its page elements (seen through wrappedJSObject, Firefox's way for a
// content script to read page objects). When the channel can't be found,
// the card is filtered as usual.

const SUBS_KEY = 'subscriptions';         // storage.local: { channels: [[id, handle]], at }
const SUBS_MAX_AGE = 24 * 60 * 60 * 1000; // refetch the saved list after a day
const CHANNEL_ID_RE = /^UC[\w-]{22}$/;
const VIDEO_ID_RE = /^[\w-]{11}$/;

let subscribedIds = new Set();
let subscribedHandles = new Set();
let subsKey = '[]';     // the saved list, serialised, to skip redundant writes
let subsAt = 0;         // when the saved list was last confirmed
let subsLoaded = false;
let subsFetched = false;
const channelByVideo = new Map(); // videoId -> { id, handle }
const listCache = new WeakMap();  // element -> { list, size, byVideo }

// "/@Name/videos" -> "@name"
function normHandle(path) {
  const m = path && String(path).match(/^\/?(@[^/?#]+)/);
  if (!m) return null;
  try {
    return decodeURIComponent(m[1]).toLowerCase();
  } catch (e) {
    return m[1].toLowerCase();
  }
}

function useSubscriptions(saved) {
  const channels = Array.isArray(saved && saved.channels) ? saved.channels : [];
  subsKey = JSON.stringify(channels);
  subsAt = (saved && saved.at) || 0;
  subscribedIds = new Set(channels.map(c => c[0]).filter(Boolean));
  subscribedHandles = new Set(channels.map(c => normHandle(c[1])).filter(Boolean));
}

function storeSubscriptions(channels) {
  const fresh = Date.now() - subsAt < SUBS_MAX_AGE / 2;
  if (JSON.stringify(channels) === subsKey && fresh) return;
  const saved = { channels, at: Date.now() };
  useSubscriptions(saved);
  browser.storage.local.set({ [SUBS_KEY]: saved });
}

// The data YouTube attaches to one of its elements, or null.
function pageData(el) {
  try {
    const data = (el.wrappedJSObject || el).data;
    return data && typeof data === 'object' ? data : null;
  } catch (e) {
    return null;
  }
}

// Depth-first, in key order, through page data: the first non-null pick(node).
function findInData(root, pick, limit = 3000) {
  const stack = [root];
  for (let n = 0; stack.length && n < limit; n++) {
    const node = stack.pop();
    if (!node || typeof node !== 'object') continue;
    const found = pick(node);
    if (found) return found;
    const keys = Object.keys(node);
    for (let i = keys.length - 1; i >= 0; i--) {
      const value = node[keys[i]];
      if (value && typeof value === 'object') stack.push(value);
    }
  }
  return null;
}

// A video's data links to its channel first (avatar or byline).
function channelInData(data) {
  return findInData(data, node => {
    const b = node.browseEndpoint;
    return b && CHANNEL_ID_RE.test(b.browseId || '')
      ? { id: b.browseId, handle: normHandle(b.canonicalBaseUrl) }
      : null;
  });
}

function videoIdInData(data) {
  return findInData(data, node => {
    const id = node.videoId || node.contentId;
    return typeof id === 'string' && VIDEO_ID_RE.test(id) ? id : null;
  });
}

function cardVideoId(card) {
  for (const a of card.querySelectorAll('a[href]')) {
    const m = a.getAttribute('href').match(/[?&]v=([\w-]{11})|^\/shorts\/([\w-]{11})/);
    if (m) return m[1] || m[2];
  }
  return null;
}

// Home, search and subscription cards link to the channel (avatar, name).
function channelFromLinks(card) {
  for (const a of card.querySelectorAll('a[href^="/@"], a[href^="/channel/UC"]')) {
    const href = a.getAttribute('href');
    const id = href.match(/^\/channel\/(UC[\w-]{22})/);
    if (id) return { id: id[1], handle: null };
    const handle = normHandle(href);
    if (handle) return { id: null, handle };
  }
  return null;
}

function channelFromOwnData(card) {
  const inner = card.querySelector('ytd-video-renderer, ytd-compact-video-renderer, ytd-grid-video-renderer');
  for (const el of [card, inner]) {
    const data = el && pageData(el);
    const channel = data && channelInData(data);
    if (channel) return channel;
  }
  return null;
}

// Watch-page sidebar and history cards only show the channel's name, but the
// list around them holds each video's data, channel included.
function channelFromListData(card, videoId) {
  for (let el = card.parentElement; el && el !== document.body; el = el.parentElement) {
    const data = pageData(el);
    const list = data && (data.contents || data.items);
    if (!list || typeof list.length !== 'number') continue;
    let entry = listCache.get(el);
    if (!entry || entry.list !== list || entry.size !== list.length) {
      entry = { list, size: list.length, byVideo: new Map() };
      for (let i = 0; i < list.length; i++) {
        const id = videoIdInData(list[i]);
        const channel = id && channelInData(list[i]);
        if (channel) entry.byVideo.set(id, channel);
      }
      listCache.set(el, entry);
    }
    const channel = entry.byVideo.get(videoId);
    if (channel) return channel;
  }
  return null;
}

// On a channel's own pages the cards don't name the channel; the URL does.
function pageChannel() {
  const id = location.pathname.match(/^\/channel\/(UC[\w-]{22})/);
  if (id) return { id: id[1], handle: null };
  const handle = normHandle(location.pathname);
  return handle ? { id: null, handle } : null;
}

function isSubscribed(channel) {
  return !!channel && ((!!channel.id && subscribedIds.has(channel.id)) ||
                       (!!channel.handle && subscribedHandles.has(channel.handle)));
}

function fromSubscribedChannel(card, kind) {
  if (!subscribedIds.size && !subscribedHandles.size) return false;
  try {
    // Shorts' data doesn't include the channel, so only the page can tell.
    if (kind !== 'short') {
      const videoId = cardVideoId(card);
      let channel = videoId && channelByVideo.get(videoId);
      if (!channel) {
        channel = channelFromLinks(card) || channelFromOwnData(card) ||
                  (videoId && channelFromListData(card, videoId));
        if (channel && videoId) {
          if (channelByVideo.size > 5000) channelByVideo.clear();
          channelByVideo.set(videoId, channel);
        }
      }
      if (channel) return isSubscribed(channel);
    }
    return isSubscribed(pageChannel());
  } catch (e) {
    return false;
  }
}

// The guide (left sidebar) lists every subscription, including those behind
// "Show more". It isn't loaded on every page, so the list is saved.
function readGuide() {
  const guide = document.querySelector('ytd-guide-renderer');
  const data = guide && pageData(guide);
  const items = data && data.items;
  if (!items) return;
  let section = null;
  for (let i = 0; i < items.length && !section; i++) {
    section = items[i].guideSubscriptionsSectionRenderer || null;
  }
  if (!section) return; // signed out, or no subscriptions shown
  const channels = [];
  const collect = list => {
    for (let i = 0; list && i < list.length; i++) {
      const entry = list[i].guideEntryRenderer;
      const b = entry && entry.navigationEndpoint && entry.navigationEndpoint.browseEndpoint;
      if (b && CHANNEL_ID_RE.test(b.browseId || '')) channels.push([b.browseId, b.canonicalBaseUrl || null]);
      const more = list[i].guideCollapsibleEntryRenderer;
      if (more) collect(more.expandableItems);
    }
  };
  collect(section.items);
  if (channels.length) storeSubscriptions(channels);
}

// When the guide isn't loaded (e.g. a video opened directly) and the saved
// list is missing or old, read the "All subscriptions" page instead. At most
// once per tab.
async function fetchSubscriptions() {
  if (subsFetched || !settings.showSubscribed || !subsLoaded) return;
  if (Date.now() - subsAt < SUBS_MAX_AGE) return;
  subsFetched = true;
  try {
    // content.fetch sends the request as the page would, with its cookies.
    const init = { credentials: 'same-origin', redirect: 'error' };
    const res = typeof content !== 'undefined' && content.fetch
      ? await content.fetch('/feed/channels', init)
      : await fetch('/feed/channels', init);
    const m = (await res.text()).match(/var ytInitialData = (\{.*?\});<\/script>/s);
    if (!m) return;
    const channels = [];
    const stack = [JSON.parse(m[1])];
    while (stack.length) {
      const node = stack.pop();
      if (!node || typeof node !== 'object') continue;
      const c = node.channelRenderer;
      if (c && CHANNEL_ID_RE.test(c.channelId || '')) {
        const b = c.navigationEndpoint && c.navigationEndpoint.browseEndpoint;
        channels.push([c.channelId, (b && b.canonicalBaseUrl) || null]);
        continue;
      }
      for (const key of Object.keys(node)) stack.push(node[key]);
    }
    if (channels.length) {
      storeSubscriptions(channels);
      filterVideos();
    }
  } catch (e) {
    // Signed out or the page changed: keep the saved list.
  }
}

function shouldHide(card, target) {
  if (settings.minViews <= 0 || card.closest(SKIP_CONTAINERS)) return false;
  const { views, watching } = readViewCount(target);
  if (views === null || views >= settings.minViews) return false;
  const kind = cardKind(target, watching);
  if (!isKindFiltered(kind)) return false;
  return !(settings.showSubscribed && fromSubscribedChannel(target, kind));
}

function filterVideos() {
  if (settings.showSubscribed) readGuide();
  const seen = new Set();
  for (const card of document.querySelectorAll(CARD_SELECTOR)) {
    const target = hideTarget(card);
    if (seen.has(target)) continue;
    seen.add(target);

    // YouTube recycles card elements when navigating, so every card is
    // re-evaluated on each pass instead of being marked as done.
    setHidden(target, shouldHide(card, target));
  }

  const shelves = new Set(Array.from(document.querySelectorAll(SHELF_SELECTOR), shelfHideTarget));
  for (const shelf of shelves) {
    const cards = Array.from(shelf.querySelectorAll(CARD_SELECTOR));
    setHidden(shelf, cards.length > 0 && cards.every(card => hideTarget(card).hasAttribute(HIDDEN_ATTR)));
  }
}

let pending = false;
function scheduleFilter() {
  if (pending) return;
  pending = true;
  setTimeout(() => {
    pending = false;
    filterVideos();
  }, 150);
}

function applySettings(values) {
  settings = { ...settings, ...values };
  settings.minViews = Math.max(0, Number(settings.minViews) || 0);
  filterVideos();
  setTimeout(fetchSubscriptions, 3000); // give the guide a chance to load first
}

const style = document.createElement('style');
style.textContent = `[${HIDDEN_ATTR}] { display: none !important; }`;
(document.head || document.documentElement).appendChild(style);

browser.storage.sync.get(DEFAULT_SETTINGS).then(applySettings);

browser.storage.local.get(SUBS_KEY).then(result => {
  if (!subsAt) useSubscriptions(result[SUBS_KEY]); // unless the guide was already read
  subsLoaded = true;
  filterVideos();
  setTimeout(fetchSubscriptions, 3000);
});

browser.storage.onChanged.addListener((changes, area) => {
  if (area === 'local') {
    if (changes[SUBS_KEY]) {
      useSubscriptions(changes[SUBS_KEY].newValue);
      scheduleFilter();
    }
    return;
  }
  if (area !== 'sync') return;
  const values = {};
  for (const key of Object.keys(DEFAULT_SETTINGS)) {
    if (changes[key]) values[key] = changes[key].newValue ?? DEFAULT_SETTINGS[key];
  }
  if (Object.keys(values).length) applySettings(values);
});

new MutationObserver(scheduleFilter).observe(document.documentElement, {
  childList: true,
  subtree: true,
  characterData: true,
});
