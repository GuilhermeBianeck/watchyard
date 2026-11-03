# Suggested activity groups

Open **Activity → Suggested activity groups** to review which person and vehicle
events may belong together. Each entry shows its camera, time and reason. Use
the camera button to open that event's replay. This preview does not change
alert delivery, replay storage or the original event list.

Watchyard examines up to 240 recent person and vehicle events from the past
seven days. On one camera, it looks for repeated activity in the same part
of the image. Person activity can continue after a gap of up to two minutes,
with groups capped at five minutes. Overlapping person tracks on the same
camera stay separate. Vehicle correlation uses the time that movement was
confirmed, so a parked track cannot extend a group through its presence.

Across cameras, Watchyard considers close timing, coarse color similarity
and agreement between available plate readings. Conflicting plates block a
merge. It can learn directional camera relationships from repeated, separated
matches with stronger evidence. The preview recalculates from recent history
and requires no configured camera pairs. It stores coarse color and position
with new events, without a separate crop or face data. Earlier events can
produce timing-only suggestions, which are weaker and cannot train the camera
relationships. Similar clothing or vehicle color can still yield a mistaken
suggestion. In a tie between candidate groups, the event stays separate.

Compare suggestions against the replays of real visits and independent activity
before using the rules to suppress any notification.
