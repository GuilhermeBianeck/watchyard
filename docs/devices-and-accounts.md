# Devices and Telegram accounts (0.4)

An owner can register other browser devices and Telegram accounts in
Settings → Devices & accounts → Add. Existing dashboard sessions and the original
Telegram account are preserved with management access during migration. The Mac
also retains its configured local management access.

## Register a phone or desktop browser

1. Choose Phone or desktop browser, give it a name, and choose access.
2. Create the invitation and share its private link with the intended person.
3. On the new device, connect to home Wi-Fi (or the configured private VPN), open
   the link, name the browser and connect. The invitation code is prefilled.
4. The registered browser appears in the owner's device list. Revoke it there
   to stop new API requests immediately.

Invitations expire after 15 minutes and work once. Only hashes are retained;
copy the link when created or cancel and generate a new one. They do not expose
NVR or bot credentials. Browser links use the server's network address even if
created from localhost on the Mac. A browser session lasts 30 days. Safari,
Home Screen web apps and separate browsers can have separate sessions. Device
names are labels, not hardware fingerprints. Reopening an invitation in an
already signed-in browser keeps the current session; use the intended new
browser or sign out first.

The existing owner dashboard code also signs in additional management devices.
Keep that code private; use invitations to give someone view-only access.
Resetting the owner code/session key invalidates all browser sessions and pending
invitations. Previously revoked sessions cannot recreate themselves after a
restart. Signing out also revokes the server-side session.

## Register another Telegram account

Choose Telegram account and share the generated bot invitation link. The person
must open it using the intended account and tap Start. Only private bot chats
with matching Telegram user/chat identity can enroll. Groups and forwarded user
identities are not supported. One Telegram account can use the same approved bot
chat on its mobile and desktop apps; these are not separate account registrations.

Approved accounts can request `/status`, `/snapshot` and `/events`. They receive
future camera alerts with snapshots by default. Use `/notifications off` to pause
only that account's alerts and `/notifications on` to resume. This does not mute
the home or prevent on-demand snapshots. Revoke an account in the dashboard to
stop future commands and alert delivery. Already-delivered pictures cannot be
recalled by revocation.

## Access levels

- **View only:** camera previews, event history, CSV export and read-only status.
  Telegram accounts can request snapshots and control their own alert subscription.
- **Manage home:** additionally change alert rules, global mute, event reviews,
  and device/account invitations and revocation. Choose this deliberately.

New invitations default to View only. Permissions are checked on the server;
management controls are also disabled in the viewer interface. The app does not
provide public self-registration, email/password accounts or internet dashboard
access. The existing private-network allowlist still applies. Telegram itself
works over the internet without exposing the dashboard or NVR.

## Delivery and storage

The bot has one poller and multiple approved recipient accounts. Replies to a
command go only to the requesting account. Camera alerts and queued health
notices use per-recipient delivery records so a failure for one account does not
cause retries to accounts that already accepted the message. Paused/revoked
recipients are skipped on retry. A newly registered account is not added to an
already-started delivery batch. Notifications still expire after three minutes;
partly delivered events are marked accordingly. Telegram API acceptance does
not prove that a phone displayed or a person read an alert; ambiguous network
failures may still cause duplicates.

Device/invitation records are stored in private `members.db`, alongside the
existing `events.db`. Revocation tombstones are retained so old signed sessions
cannot return. Include members.db in secure migration/backup, using SQLite
backup or stopping all writers. The watchdog reads the same registry and does
not reactivate revoked accounts. No additional Telegram accounts are enrolled
until an owner invitation is used.
