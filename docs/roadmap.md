# Story and milestones

As a homeowner, I want to know when a person, moving vehicle or animal enters a relevant part of my property, so that I get fewer alerts caused by foliage and lighting while keeping the existing NVR recording.

## M1: Local foundation — implemented
- Connect four RTSP substreams with reconnection and local Core ML object detection.
- Build a local dashboard, camera health and startup service.
- Pair a single private Telegram chat and deliver a test snapshot.
- Acceptance: four fresh views, successful inference, verified pairing and automated rule tests.

## M2: Field pilot — instrumented, field validation in progress
- Walk through each camera's view by day and night; test vehicle arrival and pets where safe.
- Useful/False alarm review and CSV export implemented. Review events and missed events against NVR footage; define zones and calibrate thresholds.
- Per-minute memory and inference sampling plus Telegram-acceptance latency implemented. Observe thermals, sleep, reconnects and accuracy over several days; no sustained results claimed yet.
- Acceptance: user reviews real alerts and agrees the false-alarm/miss balance is acceptable. No accuracy target is claimed before a representative dataset exists.

## M3: Reliability and control — partly implemented in 0.3
- Implemented: durable offline/recovery queue, independent same-Mac service watchdog and delivery diagnostics. A heartbeat outside the Mac remains planned.
- Implemented: notification severity by camera/object, weekday and overnight schedules. Tracking and cross-camera re-identification remain future work.
- Home Wi-Fi dashboard access and iPhone layout: implemented in 0.2, with authenticated sessions. Internet/VPN access and short event clips remain planned.
- Acceptance: recovery and outage scenarios pass documented end-to-end checks without exposing the NVR.

## M4: Optional enhancements — planned
- Evaluate a local vision-language model for optional event descriptions; never silently suppress a person alert based on an unvalidated model.
- Explore additional classes and tailored models if field evidence warrants them.

## Alternative deployment — repository preparation

Linux CPU runtime, explicit network configuration and a private Docker Compose
profile are prepared for a future VPS. No migration or VPS deployment has taken
place. Image build, private VPN routing, throughput, transfer/storage costs and
Linux field validation remain acceptance requirements. See vps-deployment.md.
