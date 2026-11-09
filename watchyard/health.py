"""Batch timing and presentation for camera health transitions."""

OUTAGE = 'camera-outage'
RECOVERY = 'camera-recovery'
OUTAGE_SECONDS = 45
RECOVERY_SECONDS = 30
COALESCE_SECONDS = 30
REPORT_UNDELIVERED_AFTER = 600


def camera_message(kind, changes):
    if len(changes) == 1:
        camera, = changes.values()
        if kind == OUTAGE:
            return f"{camera['name']} is unavailable. Watchyard will keep trying to reconnect."
        return f"{camera['name']} recovered after {camera['duration']} seconds."
    state = 'are unavailable. Watchyard will keep trying to reconnect.' if kind == OUTAGE else 'recovered.'
    lines = [f'{len(changes)} cameras {state}']
    for camera in changes.values():
        detail = f" ({camera['duration']}s offline)" if kind == RECOVERY else ''
        lines.append(f"• {camera['name']}{detail}")
    return '\n'.join(lines)
