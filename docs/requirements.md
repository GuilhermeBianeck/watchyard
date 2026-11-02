# Requirements

## Goal
Reduce irrelevant motion notifications from four locally connected NVR cameras while preserving evidence and delivering useful alerts to an iPhone without a paid subscription.

## Functional requirements

1. Connect to each camera's low-resolution RTSP stream, decode continuously and reconnect on interruption.
2. Detect people, vehicles, dogs and cats locally; avoid sending raw streams to a cloud model.
3. Confirm objects over multiple observations, track visits, suppress repeat notifications, and require displacement for vehicle events.
4. Allow per-camera alert zones, categories and enable/disable settings; full view is the initial zone.
5. Persist confirmed event timestamps, labels, confidence, camera, delivery state and snapshots. Delete after the configured retention period.
6. Pair one private Telegram chat using a random code and accept commands only from the paired user.
7. Deliver one photo and caption for each eligible event. Send animal events silently. Retry transient failures with bounded retention and mark stale events as expired.
8. Provide `/status`, `/snapshot`, `/events`, `/mute`, `/unmute` and `/help`; detection continues during mute.
9. Provide a local dashboard with four live snapshots, health, event history, rules, mute and test notification.
10. Report camera disconnection and recovery when the Telegram connection is available.
11. Start at user login, recover from process failure, and expose a truthful health endpoint.
12. Keep credentials and images outside Git; serve the dashboard on the home network with device sign-in; keep Python on loopback and reject foreign Host, Origin and subnet access.

## Acceptance and boundaries

The application is ready for an initial pilot when all four streams are fresh, the detector runs successfully on each, the verified chat receives a test snapshot, event rules and access controls pass automated tests, and a person can test a walk-through. Record day/night precision, missed events, resource use and user feedback before relying on the system. Push delivery is best effort; it is not a certified alarm. Continuous recording remains on the NVR. No facial recognition, internet access to the dashboard, audio analysis or generative model is included in this release.
