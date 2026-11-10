# Watchyard roadmap

## Current status

Watchyard 0.8.14 is in a local field pilot on an Apple Silicon Mac. The four
installed cameras use shared ingest and a 1 fps analysis target, with live
viewing up to 10 fps. The recorder handles continuous recording. The dashboard
provides live views, event history, adaptive replays and saved clips. Telegram
delivers one alert per activity group per account and links to both the replay
and the related camera views. Grouping now uses confirmation order, trajectory
endpoints and recurring routes. Camera outages and recoveries that happen close
together send one health summary per phase and destination.

Fresh installs can create the owner account in the local dashboard.
Incident simulation can record local review decisions using manual presence and
expected or restricted camera areas. Validate these decisions on the installed
cameras before starting the presence automation, MCP and calling pilot.
[Incident escalation specification](escalonamento-inteligente.md)
The core product is deployed. Alert accuracy and grouping still need broader
validation across real day and night activity. Plate reading runs as a pilot on
one camera, with a multi-frame agreement rule. Real-world plate reliability is
unverified. Face matching remains off because the available footage did not
establish reliable matching. Pushover and signed webhooks are available as
opt-in providers. See the [latest release](https://github.com/GuilhermeBianeck/watchyard/releases/latest).

## Next work, in order

1. **Validate grouped alerts in the field.** Compare Watchyard activity and
   actual Telegram delivery against known visits, arrivals and separate people
   or vehicles. Count repeat pushes, mistaken merges, missed activity and time
   to the first alert. Pay particular attention to timing-only matches before
   widening any correlation windows. [Person alerts](https://github.com/GuilhermeBianeck/watchyard/issues/2)
   · [Vehicles and pets](https://github.com/GuilhermeBianeck/watchyard/issues/3)
2. **Check overnight stability and recovery.** Track per-camera frame age,
   reconnections, replay wait and alert latency. Exercise recorder, network and
   host interruptions. Measure live startup on a physical phone, and add an
   independent heartbeat for complete host outages.
   [Stability](https://github.com/GuilhermeBianeck/watchyard/issues/4)
   · [External heartbeat](https://github.com/GuilhermeBianeck/watchyard/issues/5)
3. **Validate recognition before expanding it.** Try close, slow Portão passes
   by day and night and compare any stored reading to the actual plate.
   Compare the larger detector with the current one on a broader private set
   of people, vehicles and pets before switching. Revisit face matching only
   if the camera captures consistently usable faces and enrollment is wanted.
4. **Evaluate remote access when needed.** The repository has a private Linux
   Compose profile. Building and running the Linux image, testing private VPN
   routing, and benchmarking the actual streams remain open. A native rewrite
   is deferred. Revisit a native worker if measured load or latency warrants it.
   [Remote review](https://github.com/GuilhermeBianeck/watchyard/issues/7)
   · [VPS setup](vps-deployment.md)

Optional local event descriptions remain a separate experiment. They are
outside the path that decides whether to send an alert.
[Event descriptions](https://github.com/GuilhermeBianeck/watchyard/issues/8)

## Milestones

| Milestone | Status |
| --- | --- |
| M1 · Local foundation | Complete. Local camera inference, dashboard and Telegram delivery. |
| M2 · Field pilot | In progress. Real-world false alarms, misses, and grouping quality. |
| M3 · Reliability and control | In progress. Durable delivery, local watchdog, schedules and diagnostics shipped. External heartbeat and sustained recovery checks remain. |
| M4 · Optional enhancements | Open. Event descriptions and recognition experiments are separate from core delivery. |
| M5 · Replay and saved clips | Complete. Recorder playback, saved clips and authenticated downloads. Replays now include context around the tracked activity. |
| M6 · Live viewing and analysis rates | Complete. On-demand 720p/10 fps live feeds and separate analysis at 1 or 2 fps. |
| M7 · Overlays and delivery options | Complete. Stable display overlays, configurable camera inventory and optional providers. |
| M8 · Shared ingest and quieter Telegram alerts | Shipped in 0.8.3–0.8.7. Shared capture and live decoding, automatic activity groups, per-account Telegram suppression and replay links. Field validation continues in M2. |
