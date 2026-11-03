# Architecture and operations

Configured RTSP streams feed one FFmpeg capture worker per camera. The shared detector processes the latest frames, and per-camera tracking and zone rules decide which events to save. SQLite stores the local event and delivery state. Enabled adapters deliver alerts to Telegram, Pushover, or a custom webhook.

The service uses macOS VideoToolbox where available and falls back to software decoding. The detector receives camera frames sequentially and handles the four supported COCO categories. The tracker confirms repeated observations and checks the bottom center of bounding boxes against a polygon. The simple nearest/overlap tracker can lose identities when objects overlap; it does not perform face recognition or re-identification across cameras.

Files in `~/Library/Application Support/Watchyard`: `secrets.json` (mode 0600), `settings.json`, `events.db`, event images, model, runtime and logs. The Node.js gateway listens on port 8765 on the home network and forwards to Python on 127.0.0.1:8766. It overwrites forwarded client identity; Python trusts these headers only from loopback. Host, Origin and subnet checks apply. Off-device API and picture requests require a signed HttpOnly, SameSite session. An eight-digit dashboard code is stored only as a keyed hash with rate-limited login attempts. Resetting its signing key revokes sessions. Transport is local HTTP, so use a trusted home network. Separate per-user LaunchAgents start the detector and web gateway at login; the detector runs under caffeinate; no port forwarding is configured. Telegram bot credentials must be rotated through BotFather if exposed. Update secrets locally and restart the service after rotation.

The detector may miss objects or hallucinate them; a quiet period is not proof of absence. Alert data leaves the host when a provider is enabled; provider or internet outages delay delivery. Camera offline notifications originate from the Mac and cannot report its own failure. Recording and NVR settings are not controlled by this service.

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

Version 0.5 adds an independent, serial replay worker and `clips.db`. An explicit
request copies alert metadata into a durable job, checks the NVR clock/search
results and fetches a bounded RTSP playback range. FFmpeg makes an H.264 MP4 and
poster in private `clips/`; the API serves authenticated byte ranges and downloads.
Kept clips survive event retention and cache eviction. The detector and Telegram
delivery loops do not wait for replay conversion. See replay-and-clips.md for
the tested recorder, resource limits and storage semantics.

Version 0.6 separates live viewing from raw analysis capture. Authenticated HLS
requests lazily start a shared FFmpeg encoder for that camera; a small private
segment cache is served through the same API and gateway. Encoders stop after
20 idle seconds. Native HLS or a locally bundled HLS.js player handles viewing.
Analysis capture now samples at the chosen 1/2 fps, with detector scheduling and
confirmation timing independent of live playback. See live-view.md.

The camera inventory maps stable IDs to a source adapter and optional replay
tracks. Capture and HLS resolve upstream URLs through the same adapter. A separate
display cache holds recent boxes across missed inference frames; the event tracker
continues to use raw detections. Notification adapters consume the same event
and health outboxes with independent delivery state per destination.


Shared ingest in 0.8.3 combines live video and sampled analysis frames in one
FFmpeg worker while a feed is watched. Dedicated capture resumes when viewing
ends or the shared worker fails. The local installation enables this on all four
cameras.

Activity correlation stores group assignments and suppresses repeat Telegram
deliveries per account after Telegram accepts an alert for the group. Each
member retains its own replay. The optional macOS plate reader samples the
recorder main stream after a vehicle event and stores only readings that agree
across multiple frames. See [activity groups](activity-correlation.md) and
[plate reading](cameras-and-notifications.md#plate-reading-pilot-on-macos).
