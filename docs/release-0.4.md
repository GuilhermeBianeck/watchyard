# Watchyard 0.4 — devices and shared access

An owner can now approve additional phone/desktop browsers and private Telegram
accounts in Settings → Devices & accounts. Each invitation works once, expires
after 15 minutes and defaults to view-only access. Management access is an
explicit choice. Existing sessions and the original Telegram account keep their
access.

Registered devices and accounts can be revoked independently. Sign-out revokes
the browser's server-side session, so a copied cookie cannot be reused afterward.
Telegram command replies go only to the requester; `/notifications on|off`
changes only that account's subscription. Camera and health alerts record each
recipient's delivery separately, avoiding retries to accounts that already
accepted an alert when another account fails.

The Mac deployment stays local. Browser access still requires the allowed
private network; Telegram accounts can use their mobile and desktop clients over
the internet. No VPS was provisioned. Future migration documentation now includes
the device registry and revocation records.

## Verification

- 61 automated tests pass, including private Telegram identity validation,
  one-use/concurrent enrollment, role enforcement, persistence, immediate
  revocation, cookie replay rejection and per-recipient event/health retries.
- JavaScript syntax and Git whitespace checks pass.
- Running LAN API verification passed browser enrollment, view-only reads,
  management rejection, invitation reuse rejection and immediate revocation.
  The temporary verification browser was revoked afterward.
- The invitation form was inspected at a 390 × 844 mobile viewport.
- Post-install checks returned readiness 200, fresh JPEGs and fresh Core ML
  detection on all four cameras. Two approved Telegram accounts were visible.

These checks verify implementation and the deployment at release time. They do
not replace the day/night detection field pilot or prove phone notification
delivery. See devices-and-accounts.md for registration and alerts-and-reliability.md
for delivery limitations.
