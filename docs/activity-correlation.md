# Activity groups

Open **Activity → Activity groups** to see related person and vehicle events.
Each entry shows its camera, time and reason and links to that view's replay.
Telegram sends an alert per episode to each account. A first alert is immediate;
a likely person return can wait up to four seconds for another camera to
corroborate its existing group. A later
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
  A low-confidence person detection can briefly continue an already confirmed
  track when there is a unique spatial match. A return after up to two minutes
  out of view can join a group from the last ten minutes when the person
  retraces the path in the same camera and upper and lower clothing match
  at two distinct positions. An overlapping person or more than one matching
  group prevents this association. The local samples exclude the face.
  Overlapping people stay separate except for very brief overlaps with
  near-identical detections, which can be treated as track fragments.
- **Later-confirmed views.** A person returning within two minutes to a similar
  position and appearance can briefly wait if the old group was observed
  within the last minute. Joining requires a simultaneous second view that
  independently continues that group and agrees with an established camera
  route. Timing alone, colour conflicts, co-visible competing people and
  ambiguous groups cannot provide this corroboration. If it is missing after
  four seconds from detection, the new alert proceeds. The deadline survives
  restarts, other notification providers do not wait, and an account that
  missed the first alert still receives this one. Existing group IDs stay fixed.
- **Across cameras.** Similar appearance supports longer transitions.
  Repeated, independently corroborated transitions can establish a route
  based on positions in both views, without preconfigured camera pairs.
  A learned vehicle route can bridge a visible-light view and an infrared
  view. A short, ordered handoff can use a small colour signal in a shadowed
  view. Timing alone supports only close transitions and cannot train a route.
- **Continuing vehicle movement.** Vehicle alerts require movement of several
  visible parts of the vehicle between frames. The check tolerates changes
  in brightness, which can make a parked car's detection box jump. A short
  interruption in a moving vehicle's track can be rejoined when the same
  image details appear along its path and the match is unique. The last
  verified movement is tracked separately from visibility. Strongly similar vehicles can be linked
  when a maneuver continues in another view. Older recordings can extend
  a short return to a view already in the group if the appearances agree.
  A vehicle that starts moving shortly after a person's last two observations
  at that vehicle can join the person's episode in the same view.
- **Long activities.** Ordinary groups span up to five minutes, or ten
  minutes for people with strong matches. With corroborated continuity a
  group can span up to 30 minutes. On the same camera, a person needs a
  short handoff with consistent recent direction, exit and entry positions,
  and similar appearance in two observations per track. Across cameras, the
  exit, entry and travel time must agree with at least three separate prior
  handoffs in that direction, as well as the appearance of the current tracks.
  A vehicle needs the same plate and recent movement to use the extended
  window. Competing matches keep these continuations separate so they
  can still produce an alert.

New events retain normalized positions, a box and coarse colour histograms
for correlation. Two body-colour samples can be available by confirmation. Later samples
can recover a useful cue when the viewing angle changes. Correlation uses existing detection frames and requires
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
