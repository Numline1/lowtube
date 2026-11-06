# LowTube - YouTube View Filter

A browser extension that filters out low-view videos from YouTube recommendations. Set your minimum view count threshold and enjoy a cleaner YouTube experience with only popular videos in your recommendations.

## Features

- Filter out videos with low view counts from the home feed, search results, Shorts shelves, and the "up next" sidebar on the watch page
- A shelf whose videos are all filtered out (such as a Shorts shelf) is hidden too, so no empty heading is left behind
- Customizable minimum view count threshold (set it to 0 to turn filtering off)
- Choose what the filter applies to: regular videos, Shorts, and/or live streams (live streams are compared by how many people are watching now)
- Optionally always show videos from channels you're subscribed to, however few views they have (see [Subscribed channels](#subscribed-channels))
- Support for different view count formats (e.g., "1.2M views", "100K", "2.1B")
- Real-time filtering as you scroll and navigate; threshold changes apply to open tabs immediately
- Settings persist across browser sessions
- Built for Firefox (Manifest V2, `browser.*` APIs)

Note: view counts are read from YouTube's English UI. With YouTube set to another language, videos whose count can't be parsed are left visible.

## Installation

### Firefox

1. Open Firefox and navigate to `about:debugging`
2. Click on "This Firefox" in the left sidebar
3. Click "Load Temporary Add-on..."
4. Navigate to the extension directory and select `manifest.json`

## Usage

1. Click the extension icon in your browser toolbar
2. Enter your desired minimum view count in the input field
3. Tick which kinds of content to filter: Videos, Shorts, Live streams
4. Optionally tick "Always show channels I'm subscribed to"
5. Click "Save Settings"
6. Visit YouTube and the extension will automatically filter out videos with fewer views than your specified minimum

## Default Settings

- Default minimum view count: 1,000 views
- Videos, Shorts and live streams are all filtered
- Videos from subscribed channels are filtered like any other (the exception is off)

## Subscribed channels

With "Always show channels I'm subscribed to" ticked, a low-view video stays visible when it comes from a channel you're subscribed to. This works on the home feed, search, the watch-page sidebar, history, the subscriptions feed, and a subscribed channel's own pages.

- **Shorts are still filtered**, except on the channel's own page: YouTube's data for a Short doesn't say which channel posted it.
- **Where the list comes from:** your subscriptions are read from YouTube's left sidebar when it's loaded, or else from your "All subscriptions" page on youtube.com (at most once a day). The list is kept in the extension's local storage and never leaves your browser.
- **How a video's channel is found:** from the channel link on the card where there is one, otherwise from the data YouTube keeps on the page. If the channel can't be found, the video is filtered as usual.
- Signed out, there is no subscription list, so nothing changes.

## Development

### Project Structure

```
lowtube/
├── manifest.json      # Extension configuration
├── popup.html        # Settings interface
├── popup.js          # Settings logic
├── content.js        # Video filtering logic
├── background.js     # Extension initialization
├── web-ext-config.mjs # web-ext lint/build options
├── CHANGELOG.md      # Release notes, newest version first
├── icons/           # Extension icons
│   ├── 16.png
│   ├── 48.png
│   └── 128.png
└── tests/
    ├── release_test.py   # Firefox release test (live YouTube)
    └── requirements.txt
```

### Building from Source

1. Clone the repository
2. Load the extension in your browser using the installation instructions above

### Releasing

Lint and build the package with Mozilla's [web-ext](https://github.com/mozilla/web-ext) (run from this directory; it reads `web-ext-config.mjs`):

```bash
npx web-ext lint
npx web-ext build
```

This writes `web-ext-artifacts/lowtube_-_youtube_view_filter-<version>.zip`.

Then test that exact package in Firefox. The release test starts a headless Firefox with a throwaway profile (your own profile is untouched), installs the package, and checks against live YouTube that it hides exactly the cards it should: search, the watch-page sidebar, Shorts, live streams, channel grids, every combination of the Videos/Shorts/Live toggles, threshold changes from the popup, and in-app navigation. It also checks that no shelf is left showing a heading with all of its videos hidden, and it opens the real toolbar popup. For "Always show channels I'm subscribed to" it gives the extension a made-up subscription list (half of the channels being hidden on search and the watch sidebar, then a whole channel's pages) and checks that exactly those channels' videos come back. With `--upgrade-from` it first installs the previous release and checks that saved settings survive the upgrade.

```bash
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
.venv/bin/python tests/release_test.py web-ext-artifacts/lowtube_-_youtube_view_filter-1.1.zip --upgrade-from lowtube.zip
```

Requires Firefox (on macOS it is started with `open -a Firefox`; elsewhere set `FIREFOX_BIN` if `firefox` is not on your PATH). Selenium downloads geckodriver automatically. The exit code is non-zero if any check fails, and screenshots are saved to `tests/output/`. The test declines YouTube's cookie prompt and uses English UI.

Before publishing, also check by hand while signed in to YouTube (the test runs logged out, where the home feed is empty): load the package via `about:debugging` → This Firefox → Load Temporary Add-on, and confirm the home feed hides low-view videos and Shorts without leaving gaps. With "Always show channels I'm subscribed to" ticked, confirm your subscriptions feed shows its low-view videos again. Then upload the zip to [addons.mozilla.org](https://addons.mozilla.org/developers/) for signing, and paste the new version's list from [CHANGELOG.md](CHANGELOG.md) into the "Release notes" field.

## License

This project is open source and available under the MIT License.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 
