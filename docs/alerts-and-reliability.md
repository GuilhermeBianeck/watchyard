# Alert controls and field review (0.3)

Settings → Camera alerts opens each camera's notification preferences. Each object
category can use Sound, Silent or Local history. Detection and event snapshots
continue when notifications are muted, outside scheduled hours or set to local
history. Disabling analysis in the area editor is different: that stops object
analysis for the camera.

Defaults remain unchanged: people and moving vehicles use sound, cats and dogs
are silent, and all hours are eligible. Global mute/disable takes precedence.
Telegram sound also depends on iPhone and Telegram settings.

Schedules use the selected IANA timezone (Europe/Lisbon by default), including
summer-time transitions. Weekdays identify the day a window starts. A Monday
22:00–07:00 window includes Tuesday morning until 07:00. Start is inclusive;
end is exclusive. Equal times mean the entire selected day. Events are evaluated
at their detection time. A pending event is checked again against current rules
before delivery. A new schedule does not create a new event for an already
tracked object.

## Review evidence

Open an event picture and mark Useful alert or False alarm, or use the buttons
on a new Telegram event notification. Reviews are stored locally. Clearing a
review restores Unreviewed. These labels do not automatically retrain or change
the detector. Activity → Export CSV downloads retained event metadata, reviews,
retry counts and delivery times, without images or credentials. Export is capped
at the newest 5,000 retained events.

False-alarm feedback alone cannot measure recall. Validate missed events by
walking through each view by day and night and comparing against NVR footage.
Do not perform unsafe vehicle or animal tests to collect examples.

## Reliability

Settings shows the pending alert queue, Telegram API acceptance delay, local
review counts, memory samples and recent health notices. Delay is measured from
confirmed event creation, not from the first physical movement, and does not
prove that the phone displayed or the person read the message. Old events from
before this release have no recorded send time and are excluded from delay
statistics. Samples are collected once a minute; peak process memory includes
the detector and FFmpeg processes, not all GPU/Neural Engine/system allocations.

Camera outages are debounced, stored in SQLite and sent silently through a durable
queue. A recovered camera supersedes an unsent stale offline notice. Network
failures retry with backoff. Detection-event notifications expire after three
minutes; pictures remain in local history. Ambiguous network failures can produce
a duplicate notification because Telegram does not provide an idempotency key.

An independent LaunchAgent checks dashboard/detector health. It can report service
failures while the Mac is running and internet is available. It cannot report a
powered-off, sleeping or disconnected Mac in real time. External heartbeat
monitoring needs another device or service and remains future work. Watchdog
status in the dashboard reports whether it checked in within the last minute.

## Deployment and recovery

The installer migrates the local SQLite schema before launching the detector,
gateway and watchdog. Existing camera areas and dashboard sessions are retained.
Before this deployment, event history and settings were backed up locally in
Application Support/Watchyard/backups. Service start/stop/restart controls all
three LaunchAgents. Restart after changing credentials. The Telegram command
cursor persists across restarts to reduce replayed commands.

## Field report

Run `.venv/bin/python -m scripts.field_report --hours 24` from the repository.
It reads the local database and prints aggregate camera counts, Telegram
acceptances, suppressed repeats, acceptance latency and resource samples.
**Settings → Reliability** also shows suppressed Telegram deliveries for the
past 24 hours. Counts are per destination. A repeat suppressed for two
Telegram accounts counts twice.

For a field check, note the time and intended outcome of a walk or arrival.
Compare the recorder footage, event group and Telegram messages. Include
two separate visitors or vehicles arriving close together as a negative test.
Use this ground truth to count misses and wrong merges. Delivery and review
counts by themselves cannot measure accuracy.

Analysis errors are shown per camera. A failed frame backs off that camera's
analysis while other cameras continue. The home watchdog checks overall
service health. The service tracks individual camera failures separately.
