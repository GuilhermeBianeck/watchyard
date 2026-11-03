# Camera inventory and notification providers

## Camera inventory

Stop the service before editing the data directory. Merge the example keys into the existing files, preserving credentials, access settings, and existing camera rules. Restart after any inventory or provider change. Keep both files outside the repository; set `secrets.json` permissions to `0600`. The same schema works on macOS and in the Linux Compose profile.

In `settings.json`, set the `cameras` list. This example mixes a recorder channel and a standalone camera:

```json
{
  "cameras": [
    {"id": 2, "name": "Front gate", "channel": 1},
    {"id": 9, "name": "Garage"}
  ]
}
```

- Configure 1–16 cameras. Each ID must be a unique positive integer. Keep IDs stable across restarts because retained events refer to them. The 16-camera configuration limit is not a throughput guarantee; measure inference and decoder load on your host.
- With no override URL, Watchyard uses `NVR_HOST`, `NVR_USERNAME`, and `NVR_PASSWORD` from `secrets.json`. The ANNKE/Hikvision-style adapter reads substream `<channel>02` and defaults to recording track `<channel>01`. If `channel` is omitted, the camera ID is used.
- For a standalone camera or an alternate stream path, add the complete URL to the private `CAMERA_RTSP_URLS` map using the camera ID as a string. URL-encode reserved characters in usernames or passwords. These streams are live and detection only unless an explicit `replay_track` in `settings.json` maps to a track on the configured ISAPI recorder. Set `"replay_track": null` to disable replay explicitly.

```json
{
  "CAMERA_RTSP_URLS": {
    "9": "rtsp://user:password@192.0.2.9:554/stream"
  }
}
```

Dashboard, capture, live playback, and Telegram snapshot commands all use the same inventory. Camera rules remain configurable from the dashboard. Green overlay boxes are display-only: a short missed detection keeps the last box for up to four seconds after it was seen, then removes it. Analysis-off and stale streams clear boxes. The alert tracker still requires actual observations and movement where applicable.

## Notification providers

Use `NOTIFICATION_PROVIDERS` in `secrets.json` to select one or more providers. Omit the key for the default `["telegram"]` or use an empty array for local history only. The delivery list affects outbound alerts; an already configured Telegram bot can still respond to approved users' commands.

```json
{
  "NOTIFICATION_PROVIDERS": ["telegram", "pushover", "webhook"],
  "PUSHOVER": {
    "app_token": "replace-with-your-app-token",
    "user_key": "replace-with-your-user-or-group-key",
    "attach_snapshot": false
  },
  "NOTIFICATION_WEBHOOK": {
    "url": "https://alerts.example.com/watchyard",
    "signing_secret": "replace-with-a-random-secret-at-least-32-bytes-long"
  }
}
```

**Telegram.** Configure your bot token, pair it from a private chat, and manage additional accounts under **Settings → Devices & accounts**. Each account can pause its alerts.

**Pushover.** Use your own [Pushover app token and user or group key](https://pushover.net/api). Optionally specify a `device` value to use Pushover's device targeting. With `attach_snapshot: true`, supported JPEGs are included; oversized snapshots fall back to text. Watchyard does not purchase or provision Pushover accounts. Silent alerts use low priority.

**Custom app.** Point the webhook at a receiver you control. It needs HTTPS, except for a receiver on the same host using loopback HTTP. Watchyard sends no camera images, camera addresses, or credentials in the payload. Generate the shared secret with `openssl rand -hex 32`, and store it on the Watchyard host and the receiver. The receiver can send its own push to APNs, FCM, or another service; Watchyard does not ship a native push client or manage mobile device tokens.

### Webhook contract

Watchyard sends a UTF-8 JSON POST. Event example:

```json
{
  "version": 1,
  "kind": "event",
  "id": "f1201198130a4428b606e058d8c7c61b",
  "created_at": 1793700000.0,
  "message": "Moving vehicle · Front gate",
  "silent": false,
  "event": {"camera_id": 2, "camera_name": "Front gate", "label": "car", "confidence": 0.92}
}
```

Health and manual test payloads use `kind: "health"` or `"test"` and omit `event`. Verify the signature against the **raw body** before decoding JSON. `X-Watchyard-Timestamp` is a Unix timestamp for the attempt; reject timestamps more than five minutes off. `X-Watchyard-Signature` is `sha256=` plus the hex HMAC-SHA256 of the timestamp, a period, and the raw body, using the shared secret as UTF-8. Compare with a constant-time function. Validate the version, then deduplicate by the signed payload's `kind` and `id`, also supplied as `Idempotency-Key: <kind>:<id>`. Scope that key to the sending installation if serving multiple installations.

Return 2xx after accepting the event. Watchyard does not follow redirects. Failed deliveries retry independently; another provider's successful delivery is not retried. Event delivery expires after three minutes. A timeout after a receiver accepted the request can cause a duplicate, so the receiver should keep its deduplication keys beyond the retry window.

Use the dashboard's test button to send a text-only test to all ready destinations. Provider status indicates that the server has configuration; a successful test confirms provider acceptance, not receipt on a device.
