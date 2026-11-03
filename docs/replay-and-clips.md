# Alert replay and saved clips (0.5)

Open an alert in Home or Activity and choose **Watch replay**. Watchyard searches
the recorder for that camera and time, then prepares a video that plays in the
dashboard. New Telegram event alerts have a **Replay on home Wi-Fi** link to the
same authenticated page. An approved Telegram account still needs a signed-in
browser to use the dashboard. The link grants no access by itself.

The requested context is 10 seconds before and 30 seconds after the alert. The
recorder seeks to a nearby keyframe; up to six extra seconds are requested to
allow for that seek. The app reports the resulting duration and warns about
recording gaps or a shorter result. On a fresh alert it waits until the following
30 seconds and a 15-second settling interval have passed before retrieval. A
recording may have been overwritten or may never have existed; an alert snapshot
does not prove the recorder captured video.

## Download and keep

- **Download** saves the prepared MP4 to the browser/device using its normal
  download interface. Phone browsers may offer a file preview or share sheet.
- **Keep clip** preserves a copy on the Watchyard server and adds it to
  Activity → Saved clips. Management access is required. The clip and its copied
  event metadata remain available after ordinary alert history expires.
- **Remove from Saved** makes it a temporary preview again. It is eligible for
  normal cache cleanup; it does not delete any recording from the NVR.

These are mobile playback copies: H.264 video, up to 720p, 15 fps, without audio
or detection overlays. The original recording stays on the NVR at its configured
quality and retention. Downloading a preview does not preserve the DVR original.
For original-quality or audio exports, use the recorder's existing export tools.

Temporary previews have a 24-hour idle lifetime and a 512 MB video cache limit;
older previews can be evicted earlier when the cache fills. Kept videos have a
separate 2 GB limit and are never automatically evicted. If that limit is reached,
download and remove an existing kept clip before keeping another. A free-space
reserve of 1 GB is required for preparation. These are video budgets; posters and
database metadata use additional space. Disk failure is still possible: back up
important clips or download a copy to a separate device.

## Recorder integration and resource use

The tested recorder is an N98PBK, firmware V4.75.000 build 250415. ISAPI recording
search and RTSP playback work on the installed device. Its HTTP download API
reports filename-based download only, so short clips are retrieved using RTSP
time ranges instead of downloading whole recording files. No recording settings,
clock settings or NVR files are modified.

All application timestamps are UTC. This recorder's search/playback APIs use
local wall time despite returning a Z suffix. Watchyard translates using the
offset in the recorder's reported local time, and translates search results back
to UTC. Its configured timezone is currently fixed at UTC+1. The recorder's clock
is also checked against the server; a difference over 30 seconds stops the job.
Correct clock configuration before retrying. No automatic clock adjustment is
performed. Historical footage across a recorder timezone change or daylight-saving
transition needs separate validation; this milestone is validated on the current
fixed-offset configuration. Keyframe alignment affects the first visible frame.

One background worker handles at most one conversion at a time, with eight
pending/preparing jobs allowed. Reopening an alert reuses its job or cached clip.
Apple Silicon uses VideoToolbox decode/encode; Linux uses a two-thread software
encoder. The worker has size and execution-time limits. Jobs and kept clips
survive restart, and an interrupted preparation is queued again. Linux replay
needs field validation before a future VPS migration.

## Access, storage and boundaries

View-only browsers can prepare, watch and download replays. Owners can also keep
and remove clips from Saved. All status, poster, video, download and HTTP byte
range requests require normal dashboard authentication and private-network
access. Revocation stops future requests; it cannot recall bytes or files already
received by a device. API responses never expose NVR credentials or RTSP URLs.

`clips.db` and `clips/` live in the private Watchyard data directory. Include both
in backup or migration, along with `members.db`, `events.db`, settings and protected
secrets. Stop writers or use SQLite backup for databases. The independent
watchdog does not prepare video and does not write to the clip database.

This milestone adds replay around Watchyard alerts and a kept-clip library.
Arbitrary calendar/timeline playback, recording-health monitoring, original-file
exports and sending video files through Telegram remain separate features.
