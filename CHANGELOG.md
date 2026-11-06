# Changelog

Newest version first. Each version's list is what goes into the "Release notes" field when uploading it to [addons.mozilla.org](https://addons.mozilla.org/developers/).

## 1.1

- Now also filters the "Up next" sidebar on video pages, and Shorts
- New: choose whether to filter videos, Shorts and live streams (live streams go by how many people are watching)
- New: optionally always show videos from channels you're subscribed to
- A shelf whose videos are all filtered out is now hidden instead of leaving an empty heading
- Fixed: counts in billions were misread, so very popular videos could be hidden
- Fixed: videos whose view count can't be read are no longer hidden
- Fixed: lowering the minimum now brings hidden videos back right away
- Fixed: a minimum of 0 is no longer reset to 1000 when the extension updates

## 1.0

- First release: hides YouTube videos with fewer views than a minimum you set
