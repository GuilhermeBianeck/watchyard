# Architecture and operations

Four RTSP substreams -> one FFmpeg worker per camera -> latest frame buffers -> shared Core ML detector -> per-camera object tracker and zone rules -> SQLite event queue and local JPEG -> Telegram Bot API -> iPhone.

The service uses macOS VideoToolbox where available and falls back to software decoding. The detector receives camera frames sequentially and handles the four supported COCO categories. The tracker confirms repeated observations and checks the bottom center of bounding boxes against a polygon. The simple nearest/overlap tracker can lose identities when objects overlap; it does not perform face recognition or re-identification across cameras.

Files in `~/Library/Application Support/Watchyard`: `secrets.json` (mode 0600), `settings.json`, `events.db`, event images, model, runtime and logs. The dashboard listens only on 127.0.0.1 and uses Host and Origin checks on changes. A per-user LaunchAgent starts at login and runs under caffeinate; no port forwarding is configured. Telegram bot credentials must be rotated through BotFather if exposed. Update secrets locally and restart the service after rotation.

The detector may miss objects or hallucinate them; a quiet period is not proof of absence. Telegram messages and snapshots leave the Mac; unavailable service or internet delays delivery. Camera offline notifications originate from the Mac and cannot report its own failure. Recording and NVR settings are not controlled by this service.
