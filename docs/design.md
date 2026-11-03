# iPhone and local dashboard design

Purpose: glance at four cameras at home, review recent events, and adjust alerts.

Tokens: iOS grouped background #f2f2f7, paper #ffffff, ink #1c1c1e, secondary
#6c6c70, system blue #0066d6, status green #248a3d. Dark appearance follows the
device. Native Apple system typography, 34 pt large mobile titles, 17 pt camera
names, 13 pt supporting text. Self-contained assets; no external font requests.

Home puts camera imagery first. A quiet monitoring row establishes current
status, followed by the four previews and two alert shortcuts. Activity groups
real events by date. Settings uses grouped rows and switches. The three sections
are persistent tabs on iPhone and a sidebar on desktop. Floating translucent
navigation is reserved for these controls; camera imagery has a solid surface.

The initial layout was reviewed against a generic SaaS dashboard: removed large
statistics, greeting copy, side-by-side mobile control panels and decorative
status cards. The camera mosaic, familiar place names and zone editor carry the
identity. Previews are labelled as periodically refreshed pictures, not live
video. Expanded camera views continue refreshing. Touch areas are at least
44px for primary controls, safe areas are respected, and motion is reduced when
requested. Sign-in does not disclose camera names or images before pairing.

Replay extends this layout with an event action and a native video sheet. Keep
the existing six color tokens and system type; camera footage is the focus.
The sheet reads from place/date to footage, preparation status and the two
actions: Download and Keep clip. Activity has a Saved clips shelf below its
event list. Left-aligned copy and full-width mobile media preserve the familiar
iOS layout. A separate dashboard of playback statistics or a fourth navigation
tab would add weight without helping this task, so the existing three tabs stay.
Loading, unavailable recordings, shorter clips and storage limits have explicit
states. Preparation never claims a made-up percentage.

Live viewing uses the same palette, native system typography and camera-first
layout. Each visible camera tile becomes muted video with a small connection
badge. Expanded views use native controls and a Go live action. The analysis
rate lives beside the existing detection threshold in Settings. No new page or
statistics panel is needed: the visible footage is the point of this change.
Off-screen tiles and background tabs stop loading video; snapshots remain a
fallback when streaming is unavailable.
