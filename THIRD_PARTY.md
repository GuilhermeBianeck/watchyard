# Bundled browser dependency

HLS.js 1.7.4, light UMD build, is served locally as
`watchyard/static/hls.light.min.js`. It enables live HLS video in browsers without
native HLS playback. No CDN, telemetry service or external browser request is used.

- Source: https://github.com/video-dev/hls.js
- Package: https://registry.npmjs.org/hls.js/-/hls.js-1.7.4.tgz
- License: Apache-2.0. Upstream notices are in `watchyard/static/hls-LICENSE.txt`
  and the license text is in `watchyard/static/hls-Apache-2.0.txt`.
- npm archive integrity: `sha512-3GlxGdPvT2YHvQYOt+yOzT/DEior/qJVNIylHA77kgeoBTdQQqi70GwefNEUmHQeNGyjC8U62+bruqW/Tpm+tg==`
- Bundled JS SHA-256: `482cccb3a224554f64d8c2cf0d335dba4a3819bdb726afbfddfe15de4c277d82`

The published archive integrity was verified before extracting the unmodified
browser bundle and notices. Updating it requires rechecking the dependency,
notices and browser playback.
