# Watchyard

Watchyard adds local object detection, live viewing, and useful alerts to the cameras you already own. It recognizes people, moving vehicles, dogs, and cats. It works with ANNKE/Hikvision-style recorders and standalone RTSP streams. Your recorder can continue to handle continuous recording.

- **Live:** Watch on iPhone, Android, or desktop at up to 720p and 10 fps. Analysis runs independently at 1 or 2 fps per camera. Boxes stay visible through short gaps in recognition. Shared ingest can let live video and analysis use one decoder while a camera is watched.
- **Activity:** Review events, export metadata, and watch, save, or download clips from a supported recorder. Related events can appear together across camera views.
- **Alerts:** Set zones, schedules, and sound preferences per camera. Use Telegram, optional Pushover, a signed webhook for your own app, or local history alone.
- **Incident simulation:** Set manual home presence and review what local rules would flag as urgent, with reasons and replay links.
- **Access:** Create the first owner account from the dashboard. Invite household members to the dashboard or Telegram with one-use links. Choose view-only or management access and revoke devices individually.

The core application is deployed in a local field pilot. See the [roadmap](docs/roadmap.md) for the current release, verification status and priorities.

## Get started on macOS

Use an Apple Silicon Mac with Python 3.11, Node.js 18 or later, FFmpeg, and network access to your cameras. A Telegram bot is optional.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install '.[test]'
.venv/bin/python scripts/configure.py
.venv/bin/python scripts/prepare_model.py
.venv/bin/python scripts/install_service.py
```

On a fresh install, open `http://127.0.0.1:8765` on the Mac and create your owner account before pairing Telegram. Then use your username and password from other devices at `http://<Mac-IP>:8765` on the same Wi-Fi. Existing installations can keep using their dashboard code or invitations. In iPhone Safari, choose **Share → Add to Home Screen** for quick access. Keep the Mac logged in and awake; the service starts after login. Use `sh scripts/service.sh status` to inspect it and `restart`, `stop`, or `start` to manage it.

The service stores configuration, events, clips, models, and logs under `~/Library/Application Support/Watchyard` by default. Set `WATCHYARD_DATA` to override the data directory consistently for setup and runtime. Keep credentials in its private `secrets.json`. Use only trusted home Wi-Fi for plain HTTP; use a private VPN for remote access and do not expose the dashboard or RTSP ports publicly.

## Connect cameras and alerts

[Configure the camera inventory](docs/cameras-and-notifications.md#camera-inventory) to use one or more recorder channels, independent RTSP streams, or both. Camera IDs are stable and can differ from recorder channel numbers. Recorder replay is available where a compatible track is mapped; RTSP alone supplies live video and detection.

[Configure notification providers](docs/cameras-and-notifications.md#notification-providers) to enable one or several delivery methods. Telegram is the default when paired and sends one alert per activity group per account. Pushover and custom webhooks are opt-in. A custom app can receive signed events through its own server and forward them to APNs or FCM. Use **Settings → Send test to enabled destinations** to check setup. In Telegram, use `/cameras` for the snapshot picker, `/status` for health and controls, and `/notifications` for personal alert preferences.

Camera analysis and history stay on the server. Telegram receives alert images; Pushover receives text and optionally a snapshot; webhooks receive event metadata. Review the provider settings before enabling delivery.

## Try incident simulation

From **Cameras**, open a camera’s settings and draw **Expected access** and
**Restricted access** areas. Then go to **Settings → Incident simulation**
and set home presence to **Away** for a fixed period, or **At home**. A Telegram
manager can also use `/presence away 4`, `/presence home` or `/presence paused`.
The default is **Paused**. **Recent decisions** shows why new person events
would require review and links to their replay. Simulation uses local rules
alongside ordinary alerts. See the [incident escalation specification](docs/escalonamento-inteligente.md).

## Deployment and operation

The Mac runs the dashboard gateway, detection and replay service, and a same-host watchdog. The [optional Linux / VPS profile](docs/vps-deployment.md) uses Docker Compose and a private route to your home recorder. It remains an alternative deployment path; it has not been tested against this home's live cameras on a VPS.

- [Activity grouping and Telegram suppression](docs/activity-correlation.md)
- [Optional macOS plate-reading pilot](docs/cameras-and-notifications.md#plate-reading-pilot-on-macos)
- [Live viewing](docs/live-view.md) and [recorder replay](docs/replay-and-clips.md)
- [Devices and accounts](docs/devices-and-accounts.md) and [alert rules and reliability](docs/alerts-and-reliability.md)
- [Architecture](docs/architecture.md), [requirements](docs/requirements.md), and [roadmap](docs/roadmap.md)

Run `.venv/bin/python -m pytest -q` to verify the app. Detection can miss brief movement, distant objects, or difficult lighting. Playback is buffered and boxes reflect the latest analysis, so fast movement can temporarily appear out of sync. Push delivery is best effort; the same-host watchdog cannot report when the entire host loses power or connectivity. Review the YOLO and Ultralytics AGPL terms before redistribution.
