# Watchyard 0.5 — alert replay and saved clips

Open an alert and choose **Watch replay** to view footage around the detection.
Download the prepared MP4, or choose **Keep clip** to retain it under Activity →
Saved clips. New Telegram event alerts link to the authenticated replay page on
home Wi-Fi. View-only browsers can watch and download; management access is
required to keep or remove clips from Saved.

The recorder continues storing original recordings. Watchyard retrieves clips
on demand, with one conversion at a time, and makes video-only H.264 copies up to
720p. Temporary previews use a bounded cache; kept clips have a separate 2 GB
budget and survive normal event retention. The replay sheet reports unavailable
recordings, clock errors, queue/preparation state and shorter or incomplete
results. Existing dashboard and Telegram account access are preserved.

The N98PBK recording API uses local wall time in its search/playback timestamps,
despite a Z suffix. Replay now translates between the recorder's reported offset
and application UTC. This was verified against the on-screen time and scene in a
real alert. Keyframe seeking can add extra context at the beginning.

## Verification

- 76 automated tests pass, including positive/negative/zero recorder offsets,
  queue limits, interrupted jobs, missing recordings, cache eviction, kept-clip
  retention, role enforcement, authenticated downloads, HEAD/byte-range requests
  and revocation. JavaScript syntax and Git whitespace checks pass.
- A real Entrada alert produced a 46-second, approximately 9 MB MP4, matched
  visually to the alert snapshot after correcting recorder time translation.
- Native browser playback and timeline seeking worked at a 390 × 844 viewport.
  Download produced a playable MP4. Keeping the clip persisted it in Activity
  after reloading the page and restarting the service. The direct alert link
  opened the replay in an existing dashboard tab. Desktop layout was inspected
  at 1280 × 900.
- Recording search and a decoded historical frame succeeded for all four
  cameras. A live LAN viewer could request an existing replay and read HEAD and
  video byte ranges; keeping was denied and revocation stopped subsequent reads.
- During the corrected replay job, 28 status samples had no camera/detector
  errors, a maximum detection age of 1.4 seconds and a peak service/video-process
  memory reading of 653 MB. These are observations from one local run.

See replay-and-clips.md for setup, retention and quality details. Calendar
playback, original-quality exports, recording-health monitoring and sending
video files through Telegram remain separate work. No VPS was provisioned.
