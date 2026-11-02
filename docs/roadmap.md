# Story and milestones

As a homeowner, I want to know when a person, moving vehicle or animal enters a relevant part of my property, so that I get fewer alerts caused by foliage and lighting while keeping the existing NVR recording.

## M1: Local foundation — implemented
- Connect four RTSP substreams with reconnection and local Core ML object detection.
- Build a local dashboard, camera health and startup service.
- Pair a single private Telegram chat and deliver a test snapshot.
- Acceptance: four fresh views, successful inference, verified pairing and automated rule tests.

## M2: Field pilot — in progress
- Walk through each camera's view by day and night; test vehicle arrival and pets where safe.
- Review events and missed events against NVR footage; define zones and calibrate thresholds.
- Monitor memory, thermals, sleep, reconnects and alert latency over several days.
- Acceptance: user reviews real alerts and agrees the false-alarm/miss balance is acceptable. No accuracy target is claimed before a representative dataset exists.

## M3: Reliability and control — planned
- Durable offline/recovery notifications, external heartbeat and user-visible delivery diagnostics.
- Configurable alert severity by camera, object and schedule; robust multi-object tracking and re-identification.
- Private remote dashboard access and optional short event clips.
- Acceptance: recovery and outage scenarios pass documented end-to-end checks without exposing the NVR.

## M4: Optional enhancements — planned
- Evaluate a local vision-language model for optional event descriptions; never silently suppress a person alert based on an unvalidated model.
- Explore additional classes and tailored models if field evidence warrants them.
