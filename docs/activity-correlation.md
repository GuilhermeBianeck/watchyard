# Activity groups

Open **Activity → Activity groups** to see related person and vehicle events.
Each entry shows its camera, time and reason and links to that view's replay.
Telegram sends an immediate alert per episode to each account. A later
event can add one audible alert if the first was silent and its camera rules
request sound. A repeat is skipped only after Telegram accepted an equivalent
alert for that account.
Every camera event keeps its own recording. The first alert can be sent as soon
as detection is confirmed. Pushover and custom webhooks still deliver camera
events individually.

An episode can contain distinct person and vehicle tracks. People observed
close together at the same time, or a person and recent vehicle motion in
the same part of a view, can share an episode. The normal object association
extends it to other cameras. Different vehicle groups and ambiguous episode
matches stay separate. New episode links are bounded by a ten-minute horizon.
Telegram links to the combined recordings.

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
  view. A short, ordered handoff can use a small colour signal in a shadowed
  view. Timing alone supports only close transitions and cannot train a route.
- **Continuing vehicle movement.** The last observed movement is tracked
  separately from visibility. Strongly similar vehicles can be linked
  when a maneuver continues in another view. Older recordings can extend
  a short return to a view already in the group if the appearances agree.
- **Limits.** Ordinary groups are capped at five minutes. Repeated strong
  matches can continue a person group for up to ten minutes. Vehicles are
  anchored to confirmed movement so a parked car cannot extend the window.
  Conflicting plates and equally plausible competing groups keep events separate.
  A clear appearance margin can resolve a tie between otherwise viable groups.

New events retain normalized positions, a box and coarse colour histograms
for correlation. A later body-colour sample can recover a useful cue when
the first frame was in shadow or the viewing angle changes. Correlation uses existing detection frames and requires
neither a separate image crop on disk nor a separate model. Similar clothing
or vehicles can still produce mistaken matches. Existing group IDs and replay
links are retained. New assignments are saved when Telegram delivery is first
attempted.

Activity shows **Added to existing alert** when a repeat is saved without
sending another Telegram notification. For a field check, compare the first
notification and related replays with a known walk or drive. Include two
different people or vehicles arriving close together to measure mistaken merges.


The design uses local track fragments plus appearance and time between views,
following the general approach described in [Integrating Appearance and
Spatial-Temporal Information for Multi-Camera People Tracking](https://openaccess.thecvf.com/content/CVPR2023W/AICity/html/Yang_Integrating_Appearance_and_Spatial-Temporal_Information_for_Multi-Camera_People_Tracking_CVPRW_2023_paper.html).
Watchyard uses coarse colour summaries and motion from the existing detector.
