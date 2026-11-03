# Smooth live view and independent analysis

Home now plays muted live video for the camera tiles currently visible on screen.
Tap a tile for a larger player with native controls. **Go live** reconnects at the
current live edge after a pause. If a phone blocks autoplay, tap the camera and
use its Play control. Live video is video-only, at up to 720p and 10 fps. Its small
playback buffer adds a few seconds of delay; this is not instantaneous WebRTC.

The Live badge estimates the delivered frame rate when the browser exposes frame
counters. Device load, connection quality and playback catch-up can affect the
estimate. A periodic snapshot remains available while a stream connects or if
streaming is unsupported.

## Three different rates

Previously, each capture worker produced 3 raw frames/second, the detector
targeted 2 analyses/second per camera, and Home refreshed a JPEG every 3 seconds
(about 0.33 displayed frames/second). These were separate limits.

Now the viewing and analysis paths are independent:

- **Live viewing:** a shared H.264 HLS feed at 10 fps per watched camera, using the
  recorder's 720p substream. The checked source stream itself runs at 10 fps;
  Watchyard does not change any recorder encoding settings.
- **Analysis:** configurable under Settings → Detection → Analysis rate, at 1 or
  2 fps per camera. New installations default to 1. Existing preferences survive
  upgrades; this home instance was explicitly switched to 1 fps.
- **Status/history:** metadata still refreshes every 3 seconds. That timer does
  not pace live video. A separate, lightweight overlay refresh shows recent
  detections. Boxes persist for up to four seconds across missed detections.
  Playback has a short buffer, so fast-moving objects can temporarily look out
  of sync with their boxes. Event snapshots retain their own annotations.

Three matching observations are still required. At 1 fps, confirmation normally
needs roughly two seconds of observations plus processing and capture timing.
Brief movement can be missed. The confirmation window allows modest timing
jitter, but does not turn a single detection into an alert. Choose 2 fps for faster
movement/response, then assess the effect against real day/night footage.

Lower analysis rates reduce model calls, scaling and raw frame transfers. The
analysis capture workers still receive and decode their source streams;
changing analysis fps does not change the NVR's source bitrate or recording fps.

## Resource use and lifecycle

One live encoder per camera is shared between all viewers. No live encoder is
started until an authenticated client requests its playlist. Apple Silicon uses
VideoToolbox decode/encode. The prepared Linux runtime uses a two-thread software
encoder and still needs resource/field validation for a future deployment.

Tiles outside the viewport stop loading. Opening a camera sheet pauses background
tile streams. Activity, Settings, other sheets and hidden tabs release their
live players. After 20 idle seconds, the server stops that camera's encoder and
removes its temporary files. The analysis capture workers continue running.
An encoder can also be retained by another viewer still watching that camera.

The live cache is `live/` in the private Watchyard data directory. Five one-second
segments and three extra segments are retained per active feed, plus files being
written. Restarted feeds use new segment names. This is a temporary playback
buffer, not an additional recorder; exclude it from backups and migrations.

## Access and browser support

Playlists and every video segment require the existing authenticated dashboard
session and network allowlist. View-only accounts can watch. Only management
accounts can change the analysis rate. Revocation stops new requests; a few
seconds already buffered on a device cannot be recalled.

Safari/native HLS is used when available. Other supported browsers use the pinned
HLS.js light bundle shipped with the app; no CDN or additional service is used.
The content policy allows local media and the local blob media buffers needed
by browser playback. Script and network sources remain restricted to this app.
See THIRD_PARTY.md and the bundled upstream license notices.

## Shared ingest

Set `"shared_ingest": true` on a camera in `settings.json` and restart Watchyard
to enable the shared path. It is enabled for all four cameras on the current Mac installation. It uses one FFmpeg input and decoder to produce both
H.264 HLS and sampled analysis frames while the feed is being watched. The
capture worker stays available until the shared worker produces both outputs.
When viewers leave, the dedicated worker resumes before the live worker closes,
with a bounded handoff. A failed shared worker restores dedicated capture and
falls back to separate live encoding on the next request. Remove the setting
and restart to return to the standard path.

Run `.venv/bin/python -m scripts.benchmark_ingest 1 --seconds 20` from the repo
to compare both layouts for camera ID 1. Add `--reverse` to run the shared case
first. The probe temporarily opens additional recorder connections and uses a
temporary HLS directory. It reports FFmpeg process RSS and CPU, analysis rate,
and the time until both outputs are available. Run it on one camera at a time.

On Portão, the shared command with HLS mapped first measured 84 MiB of FFmpeg
RSS versus 137 MiB for two workers. Both produced about 0.99 analysis fps and
started in about 2.6 seconds. CPU measured 4.7% versus 5.3% of one core during
that short run. These are worker measurements, not savings for the whole Mac.

A separate language benchmark compared 80 warm calls on the same prepared
640 × 640 camera frame. Direct Swift Core ML prediction had a 3.07 ms median
and 3.90 ms p95. Python through Ultralytics and Core ML had a 9.48 ms median
and 10.15 ms p95. Both returned the same class, confidence and box for that
frame. Swift reused the prepared input and did not run the production
preprocessing or tracking loop. At around four analyses per second total, the
measured difference represents about 26 ms of call time per second. It is not
a whole-service CPU benchmark. This result supports keeping the existing
application and improving its media pipeline first.
