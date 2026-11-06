// Options for Mozilla's web-ext (`npx web-ext lint`, `npx web-ext build`),
// picked up when run from this directory.
export default {
  // Keep development files out of the released package.
  ignoreFiles: ['tests', 'tests/**', 'web-ext-config.mjs', 'lowtube.zip', 'CHANGELOG.md'],
  build: {
    overwriteDest: true,
  },
};
