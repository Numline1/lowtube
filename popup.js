const DEFAULT_SETTINGS = {
  minViews: 1000,
  filterVideos: true,
  filterShorts: true,
  filterLive: true,
  showSubscribed: false,
};
const TOGGLES = ['filterVideos', 'filterShorts', 'filterLive', 'showSubscribed'];

document.addEventListener('DOMContentLoaded', function() {
  const minViewsInput = document.getElementById('minViews');
  const saveButton = document.getElementById('saveButton');
  const status = document.getElementById('status');

  // Load saved settings
  browser.storage.sync.get(DEFAULT_SETTINGS).then(function(result) {
    minViewsInput.value = result.minViews;
    for (const key of TOGGLES) {
      document.getElementById(key).checked = result[key];
    }
  });

  // Save settings. Open YouTube tabs pick the change up via storage.onChanged.
  saveButton.addEventListener('click', function() {
    const settings = {
      minViews: Math.max(0, parseInt(minViewsInput.value, 10) || 0),
    };
    for (const key of TOGGLES) {
      settings[key] = document.getElementById(key).checked;
    }
    minViewsInput.value = settings.minViews;

    browser.storage.sync.set(settings).then(function() {
      status.style.display = 'block';
      setTimeout(() => {
        status.style.display = 'none';
      }, 2000);
    });
  });
});
