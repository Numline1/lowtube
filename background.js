browser.runtime.onInstalled.addListener(function() {
  browser.storage.sync.get('minViews').then(function(result) {
    // Only seed the default once; 0 is a valid saved value ("filter nothing").
    if (result.minViews === undefined) {
      browser.storage.sync.set({ minViews: 1000 });
    }
  });
});
