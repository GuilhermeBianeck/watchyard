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
- Home Wi-Fi dashboard access and iPhone layout: implemented in 0.2, with authenticated sessions. Short event replays are implemented in 0.5. Internet/VPN access remains separate work.
- Acceptance: recovery and outage scenarios pass documented end-to-end checks without exposing the NVR.

## M4: Optional enhancements — planned
- Evaluate a local vision-language model for optional event descriptions; never silently suppress a person alert based on an unvalidated model.
- Explore additional classes and tailored models if field evidence warrants them.

## M5: Alert → replay → save — implemented in 0.5

As a homeowner, I can open an alert, watch footage around its timestamp and keep
or download a clip so that I can understand what happened without switching apps.

- Search the NVR and prepare one mobile-compatible replay at a time.
- Show recording/preparation states, unavailable footage, gaps and clock errors.
- Offer download to approved viewers and a kept-clip library managed by owners.
- Preserve kept clips after normal event history and preview-cache cleanup.
- Acceptance: real recorder retrieval, browser playback/seeking, download byte
  ranges, authorization, retention and concurrent detector health are verified.
- Calendar playback, disk/recording health and original-quality exports remain
  follow-on work rather than acceptance requirements for this milestone.

## Multi-device and account access — implemented in 0.4

As an owner, I can invite another phone, desktop browser or Telegram account so
that it can view home cameras without sharing the owner code. I choose view-only
or management access and can revoke the device/account independently.

- One-use invitations expire after 15 minutes; new invitations default to view-only.
- Named browser sessions and private Telegram accounts appear in Settings.
- Per-account Telegram alert subscriptions and per-recipient retries preserve
  private command replies and avoid repeating successful deliveries.
- Acceptance: browser sign-in, viewer authorization, immediate revocation,
  cookie replay rejection, concurrent invitation use and independent Telegram
  delivery/retries pass verification. Actual phone/desktop accounts complete
  registration by opening the owner's invitation.

## M6: Smooth live viewing and efficient analysis — implemented in 0.6

As a homeowner, I can watch smooth live video while object analysis uses a lower
independent rate, so that viewing quality is not tied to detector workload.

- Stream visible cameras and expanded views at up to 720p/10 fps.
- Share one encoder per camera between approved viewers and stop idle feeds.
- Choose a 1/2 fps analysis target, preserving repeated-observation confirmation.
- Keep playback, playlist and segment access under existing authentication.
- Acceptance: native-HLS and Chrome playback, measured delivered rate, concurrent
  analysis, viewer authorization and idle cleanup are verified locally.

## Alternative deployment — repository preparation

Linux CPU runtime, explicit network configuration and a private Docker Compose
profile are prepared for a future VPS. No migration or VPS deployment has taken
place. Image build, private VPN routing, throughput, transfer/storage costs and
Linux field validation remain acceptance requirements. See vps-deployment.md.
