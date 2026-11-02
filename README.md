# Watchyard

Local camera monitoring for an Apple Silicon Mac, with Telegram alerts for people, moving vehicles, dogs and cats. The existing NVR remains responsible for recording. Watchyard is an early pilot: verify detections and tune zones before relying on it.

## Current deployment

The dashboard runs on the Mac at http://127.0.0.1:8765 and on the home Wi-Fi using the Mac’s IP address with port 8765. Mobile devices sign in with an eight-digit dashboard code. Four NVR substreams are decoded with FFmpeg and analysed locally with YOLO11 nano and Core ML. Notifications and selected snapshots go to a paired Telegram chat. Detection and event snapshots stay on the Mac; Telegram receives the alerts and images sent to it. Telegram bot chats are not end-to-end encrypted.

The macOS services start after login and requests that the Mac stay awake. It needs network access to the NVR and internet for Telegram. A closed lid, logout, power loss or network outage may stop monitoring. A small Node.js gateway serves the dashboard on home Wi-Fi; the Python service stays on loopback. A separate watchdog is needed to notify you if the Mac itself stops.

## Use

Open the dashboard to view cameras, inspect events, set alert zones and mute notifications. In Telegram use `/status`, `/snapshot` (or `/snapshot 1` through `/snapshot 4`), `/events`, `/mute 60`, `/unmute` and `/help`. By default, people and vehicles alert audibly; dogs and cats are silent. A moving vehicle must change position before alerting. Event pictures are kept locally for seven days.

## Setup on macOS

Requires Apple Silicon, Python 3.11, Node.js 18+, FFmpeg, a local RTSP NVR and a Telegram bot. Run from the repository:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install '.[test]'
.venv/bin/python scripts/configure.py
.venv/bin/python scripts/dashboard_code.py
.venv/bin/python scripts/prepare_model.py
.venv/bin/python scripts/install_service.py
```

The configuration script prompts for credentials and creates an owner-only secrets file under `~/Library/Application Support/Watchyard`. Pair the bot using the displayed private-chat command. Do not commit credentials or event images. The model download and Python packages require internet; camera inference remains local.

Check `sh scripts/service.sh status`; use `restart`, `stop` or `start` with the same script. Logs and data are in `~/Library/Application Support/Watchyard`. Stop monitoring by running `sh scripts/service.sh stop`; this preserves the data and service configuration.

## iPhone access

Connect your iPhone to the same home Wi-Fi as the Mac. In Safari, open
`http://<Mac-IP>:8765` and enter the dashboard code. Safari’s Share menu can add
it to the Home Screen, with a dedicated icon. The Home, Activity and Settings
tabs adapt to iPhone, iPad and desktop. Appearance follows your device.
Camera pictures refresh every three seconds; these are previews rather than
continuous video. Tap a camera for an expanded view or its settings icon to
edit an alert area.

The code is separate from your NVR password. Sessions last 30 days. Sign out in
Settings, or reset the code and revoke all sessions using
`.venv/bin/python scripts/dashboard_code.py`, then restart the service. Keep the
code private. The interface uses HTTP on your trusted home Wi-Fi, not TLS; do
not forward its port to the internet. Other devices cannot fetch camera data
without signing in, and clients outside the home subnet are rejected. The Mac's
loopback address retains direct local access. If the Mac’s IP or network changes,
restart Watchyard to refresh the host/subnet allowlist. Guest Wi-Fi isolation or
a firewall rule may prevent mobile access.

## Tests and limitations

Run `.venv/bin/python -m pytest -q`. Rules require repeated detections, use the bottom of the bounding box for zones, suppress duplicates within a track and require movement for vehicles. Tracking is basic: occlusions, nighttime lighting, small distant animals and rapid motion can cause missed or duplicate alerts. Thresholds and zones trade false positives against missed events. Telegram delivery depends on internet and phone notification settings. Failed notifications retry for up to three minutes; older events remain local.

See [requirements](docs/requirements.md), [architecture](docs/architecture.md), [stories and milestones](docs/roadmap.md), and [design](docs/design.md). YOLO and the Ultralytics library use AGPL licensing; review their terms before distributing or offering this as a service.

## Release 0.3

Per-camera schedules and Sound/Silent/Local history controls are available in
Settings. Review events on the dashboard or Telegram; export retained metadata
from Activity. Reliability settings show queue state, measured delivery delay,
local reviews and the independent service watchdog. See
[alert controls and reliability](docs/alerts-and-reliability.md) for schedule
semantics, migration and outage limitations. No external service or paid
subscription was added.
