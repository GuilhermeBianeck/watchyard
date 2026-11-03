# Watchyard 0.6 — live video and independent analysis rates

Visible Home camera tiles and expanded views now play live video at up to
720p/10 fps. Each camera has one shared, on-demand encoder. Background/off-screen
players disconnect, and idle encoders stop and remove their temporary files.
The existing snapshot remains a fallback while connecting or when streaming is
unsupported. Expanded views have native playback controls and **Go live**.

Analysis is independent: Settings → Detection → Analysis rate offers 1 fps for
lower load or 2 fps for faster response. New installations default to 1 fps; this
home instance was explicitly switched to 1 fps. Capture samples at that rate,
while status/history still refresh every three seconds. Three-observation
confirmation remains in place, so lower rates can miss brief movement.

Live video uses a short HLS playback buffer and has a few seconds of delay. It is
video-only. No recorder settings, recording quality or existing alert schedules
were changed. All playlists and segments retain dashboard authentication and the
private-network restriction. HLS.js is pinned and bundled locally for browsers
without native HLS; the upstream license and integrity details are included.

## Verification

- 85 automated tests pass, including lazy/shared encoders, idle cleanup, restart
  and hardware fallback, path/generation validation, playlist and segment
  authentication, viewer role enforcement, revocation and analysis-rate controls.
- A source probe reported 1280 × 720 HEVC at 10 fps. The generated live stream
  probed as H.264 at 1280 × 720 and 10 fps, with one-second segments.
- Native HLS played in the Mac's in-app browser. Chrome used the bundled MSE
  player; all four views measured 10.0 fps from browser frame counters, with no
  media errors. Expanded playback, pause, Go live and a 390 × 844 layout were
  checked. The 1 fps preference was visible in Settings.
- A steady four-view run measured 0.91–0.92 analyses/second per camera, maximum
  analysis age 1.26 seconds, maximum inference 152.5 ms and peak service/video
  process memory of 418 MB across 12 samples. An earlier two-local-browser
  startup run had an analysis-age outlier of 9.34 seconds. These are short local
  observations; local browser decoding adds host load and memory beyond the
  service's process readings, and sustained field validation remains necessary.
- Expanding one camera left only that live encoder active after the idle grace
  period. Leaving Home stopped all live encoders and removed temporary segments,
  while analysis continued on all four cameras.
- Live LAN checks verified viewer playlist/segment access, management denial for
  analysis settings, and immediate rejection of requests after revocation.

See [live view](live-view.md) for buffering, quality, rate tradeoffs and lifecycle.
The Mac stays local; a future VPS runtime remains prepared rather than deployed.
