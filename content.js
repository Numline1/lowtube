let minViews = 0;

browser.storage.sync.get(['minViews']).then(function(result) {
  if (result.minViews) {
    minViews = result.minViews;
    filterVideos();
  }
});

browser.runtime.onMessage.addListener(function(request, sender, sendResponse) {
  if (request.action === 'updateSettings') {
    minViews = request.minViews;
    filterVideos();
  }
});

function parseViewCount(viewCountText) {
  const [, num, suffix] = viewCountText.match(/([\d,.]+)\s*([kKmM]?)/) || [];

  let views = parseFloat((num || "0").replace(/,/g, ""));

  if (/k/i.test(suffix)) views *= 1000;
  if (/m/i.test(suffix)) views *= 1000000;

  return views;
}

function getViewsText(item) {
  // Standard metadata
  const viewCountText = [...item.querySelectorAll("yt-content-metadata-view-model span")]
    .find(el => /views?/i.test(el.textContent));

  if (viewCountText) {
    return viewCountText.textContent.trim();
  }

  // End screen
  const videowallSpan = item.querySelector(
    ".ytp-modern-videowall-still-view-count-and-date-info"
  );

  if (videowallSpan) {
    return videowallSpan.textContent.trim();
  }

  return "";
}

function filterVideos() {
  const videoItems = document.querySelectorAll(`
    yt-lockup-view-model,
    ytd-video-renderer,
    ytd-rich-item-renderer,
    a.ytp-modern-videowall-still
  `);

  videoItems.forEach(item => {
    if (item.dataset.viewsProcessed) return;
    item.dataset.viewsProcessed = "true";

    const viewCountText = getViewsText(item);
    if (!viewCountText) return;

    const viewCount = parseViewCount(viewCountText);
    if (viewCount < minViews) {
      item.remove();
    }
  });
}

let timeout;
const observer = new MutationObserver(() => {
  clearTimeout(timeout);
  timeout = setTimeout(() => {
    filterVideos();
  }, 200);
});

observer.observe(document.body, {
  childList: true,
  subtree: true
});

filterVideos();
