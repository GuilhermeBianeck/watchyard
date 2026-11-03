# Activity groups

Open **Activity → Activity groups** to review which person and vehicle
events may belong together. Each entry shows its camera, time and reason. Use
the camera button to open that event's replay. Telegram sends one alert per group to each account. An account is only skipped
after Telegram accepted a different event in that group for that account.
Every event keeps its own recording and entry in Activity. The first alert
is sent without waiting for another event. Other providers keep their normal
delivery behavior.

Watchyard examines up to 240 recent person and vehicle events from the past
seven days. On one camera, it looks for repeated activity in the same part
of the image. Person activity can continue after a gap of up to two minutes,
with groups capped at five minutes. Overlapping tracks on the same camera stay separate. Vehicle correlation uses the time that movement was
confirmed, so a parked track cannot extend a group through its presence.

Across cameras, Watchyard considers close timing, coarse color similarity
and agreement between available plate readings. Conflicting plates block a
merge. It can learn directional camera relationships from repeated, separated
matches with stronger evidence. The engine learns from recent history and requires no configured camera pairs.
Group assignments are saved when delivery is first attempted. It stores coarse color and position
with new events, without a separate crop or face data. When stronger cues are missing, close timing can still group events and suppress
a repeat Telegram alert. Timing-only groups are weaker and cannot train camera
relationships. Similar clothing or vehicle color can still yield a mistaken
suggestion. In a tie between candidate groups, the event stays separate.

When reviewing Activity, an event shown as **Added to existing alert** was
saved but did not send another Telegram message. Late-arriving cues can help
future matches but cannot undo a delivery decision already made.
