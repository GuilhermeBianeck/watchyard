# Architecture and operations

Four RTSP substreams -> one FFmpeg worker per camera -> latest frame buffers -> shared Core ML detector -> per-camera object tracker and zone rules -> SQLite event queue and local JPEG -> per-recipient delivery queue -> Telegram Bot API -> approved mobile/desktop accounts.

The service uses macOS VideoToolbox where available and falls back to software decoding. The detector receives camera frames sequentially and handles the four supported COCO categories. The tracker confirms repeated observations and checks the bottom center of bounding boxes against a polygon. The simple nearest/overlap tracker can lose identities when objects overlap; it does not perform face recognition or re-identification across cameras.

Files in `~/Library/Application Support/Watchyard`: `secrets.json` (mode 0600), `settings.json`, `events.db`, event images, model, runtime and logs. The Node.js gateway listens on port 8765 on the home network and forwards to Python on 127.0.0.1:8766. It overwrites forwarded client identity; Python trusts these headers only from loopback. Host, Origin and subnet checks apply. Off-device API and picture requests require a signed HttpOnly, SameSite session. An eight-digit dashboard code is stored only as a keyed hash with rate-limited login attempts. Resetting its signing key revokes sessions. Transport is local HTTP, so use a trusted home network. Separate per-user LaunchAgents start the detector and web gateway at login; the detector runs under caffeinate; no port forwarding is configured. Telegram bot credentials must be rotated through BotFather if exposed. Update secrets locally and restart the service after rotation.

The detector may miss objects or hallucinate them; a quiet period is not proof of absence. Telegram messages and snapshots leave the Mac; unavailable service or internet delays delivery. Camera offline notifications originate from the Mac and cannot report its own failure. Recording and NVR settings are not controlled by this service.

Version 0.3 adds a separate watchdog LaunchAgent and durable health outbox. It polls the local dashboard and detector status, and delivers queued camera/service health notices independently of the detector process. The same SQLite database stores review labels, notification timestamps and per-minute resource samples. See alerts-and-reliability.md for limits.

Version 0.4 adds `members.db` for registered browser sessions, approved Telegram
accounts and invitation hashes. The original Telegram account and existing
signed browser sessions migrate with management access. New invitations default
to view-only access; authorization is enforced by the API and bot. Browser
sessions require both a valid signature and an active registry record. Revocation
and sign-out invalidate them immediately, including replayed cookies. Invitations
are kind-bound, expire after 15 minutes and are accepted atomically once. The
watchdog and detector use the same membership registry and track delivery per
recipient to avoid resending accepted alerts when another account fails. See
devices-and-accounts.md for enrollment, permissions and backup requirements.
