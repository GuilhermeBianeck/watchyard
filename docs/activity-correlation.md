# Activity groups

Open **Activity → Activity groups** to see related person and vehicle events.
Each entry shows its camera, time and reason and links to that view's replay.
Telegram sends one alert per group to each account. A repeat is skipped only
after Telegram accepted another event from that group for the same account.
Every camera event keeps its own recording. The first alert can be sent as soon
as detection is confirmed. Pushover and custom webhooks still deliver camera
events individually.

Watchyard considers up to 480 recent person and vehicle events from the past
seven days. It forms groups in confirmation order and uses the observed start
and end times for matching. A camera that confirms a person later can join an
already delivered group even if it started tracking that person earlier.

- **Same camera.** Compare the last observed position with where the next
  track began, along with its position and coarse colour at confirmation.
  Look for returns to the same area or a short tracking gap along the path.
  Overlapping people stay separate except for very brief overlaps with
  near-identical detections, which can be treated as track fragments.
- **Across cameras.** Similar appearance supports longer transitions.
  Repeated, independently corroborated transitions can establish a route
  based on positions in both views, without preconfigured camera pairs.
  A learned vehicle route can bridge a visible-light view and an infrared
  view. Timing alone supports only close transitions and cannot train a route.
- **Limits.** Ordinary groups are capped at five minutes. Repeated strong
  matches can continue a person group for up to ten minutes. Vehicles are
  anchored to confirmed movement so a parked car cannot extend the window.
  Conflicting plates and equally plausible competing groups keep events separate.

New events retain normalized positions, a box and coarse colour histograms
for correlation. Correlation uses existing detection frames and requires
neither a separate image crop on disk nor a separate model. Similar clothing
or vehicles can still produce mistaken matches. Existing group IDs and replay
links are retained. New assignments are saved when Telegram delivery is first
attempted.

Activity shows **Added to existing alert** when a repeat is saved without
sending another Telegram notification. For a field check, compare the first
notification and related replays with a known walk or drive. Include two
different people or vehicles arriving close together to measure mistaken merges.
