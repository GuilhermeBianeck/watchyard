"""Local simulation of incident review. Observations never dispatch an alert."""
import logging
import sqlite3
import time
from dataclasses import dataclass

from .policy import decision
from .rules import inside

log = logging.getLogger(__name__)
AWAY_MINUTES = (60, 240, 480, 1440)
RESTRICTED_SECONDS = 8
MAX_GAP_SECONDS = 3
MAX_AGE_SECONDS = 180


def presence(config, now=None):
    state = config.get('incident_presence', {'mode': 'paused', 'changed_at': None, 'until': None})
    now = time.time() if now is None else now
    if state['mode'] == 'away' and state['until'] <= now:
        return {**state, 'mode': 'unknown'}
    return state


def set_presence(settings, mode, minutes=None, *, now=None):
    if mode not in ('home', 'away', 'paused'):
        raise ValueError('Choose At home, Away or Paused.')
    if (mode == 'away' and minutes not in AWAY_MINUTES) or (mode != 'away' and minutes is not None):
        raise ValueError('Choose an away period of 1, 4, 8 or 24 hours.')
    now = time.time() if now is None else now
    state = {'mode': mode, 'changed_at': now, 'until': now + minutes * 60 if mode == 'away' else None}
    settings.save({'incident_presence': state})
    return state


@dataclass
class Trace:
    started: float
    last: float
    zone: str
    since: float
    samples: int = 1
    entered: bool = False
    saved: tuple | None = None

    def update(self, zone, now):
        if now - self.last > MAX_GAP_SECONDS or zone != self.zone:
            self.entered = zone == 'restricted' and self.zone != 'restricted' and now - self.last <= MAX_GAP_SECONDS
            self.zone, self.since, self.samples = zone, now, 1
        else:
            self.samples += 1
        self.last = now


def assess(config, camera, home, trace, stamp):
    mode, reason = decision(config, camera, 'person', stamp)
    if mode == 'off':
        return 'held', reason
    if home == 'home':
        return 'ordinary', 'Presence is set to At home.'
    if trace.zone == 'expected':
        return 'ordinary', 'Person observed in the expected access area.'
    if trace.zone == 'unmapped':
        return 'ordinary', 'No review area is configured here.'
    if trace.zone != 'restricted':
        return 'ordinary', 'Person observed outside the configured review areas.'
    if trace.last - trace.started > MAX_AGE_SECONDS:
        return 'observe', 'Incident is past the review window.'
    if not trace.entered:
        return 'observe', 'Person in the restricted area. Entry was not observed.'
    if trace.samples < 3 or trace.last - trace.since < RESTRICTED_SECONDS:
        return 'observe', 'Entry observed. Waiting for sustained activity in the restricted area.'
    if home == 'unknown':
        return 'urgent', 'Sustained activity after a restricted-area entry. Home presence is unknown.'
    return 'urgent', 'Sustained activity after a restricted-area entry while set to Away.'


class IncidentSimulation:
    def __init__(self, store):
        self.store = store
        self.cameras = {}

    def observe(self, camera, tracks, config, observed, captured):
        home = presence(config, captured)
        camera_id = camera['id']
        if home['mode'] == 'paused' or captured < home['changed_at']:
            self.cameras.pop(camera_id, None)
            return

        restricted = camera.get('restricted_zone', [])
        expected = camera.get('expected_zone', [])
        context = (home['mode'], home['changed_at'], restricted, expected, camera['zone'])
        previous_context, previous = self.cameras.get(camera_id, (None, {}))
        active = {}
        self.cameras[camera_id] = (context, active)
        for track in tracks.values():
            if track.label != 'person':
                continue
            key = (track.id, track.first)
            trace = previous.get(key) if previous_context == context else None
            if track.last != observed:
                if trace:
                    active[key] = trace
                continue
            foot = ((track.box[0] + track.box[2]) / 2, track.box[3])
            zone = 'unmapped' if not restricted and not expected else 'outside'
            if restricted and inside(foot, restricted):
                zone = 'restricted'
            elif expected and inside(foot, expected):
                zone = 'expected'
            if trace is None:
                trace = Trace(track.first, observed, zone, observed)
            else:
                trace.update(zone, observed)
            active[key] = trace
            if track.event_id:
                self.save(track.event_id, trace, config, camera, home['mode'], captured)

    def save(self, event_id, trace, config, camera, home, captured):
        outcome, reason = assess(config, camera, home, trace, captured)
        signature = (event_id, outcome, reason)
        if trace.saved == signature:
            return
        try:
            self.store.save_incident_assessment(
                event_id, captured, home, outcome, reason, trace.zone,
                trace.samples, round(trace.last - trace.since, 1),
            )
        except sqlite3.Error:
            log.warning('Could not save incident simulation on camera %s', camera['id'])
            return
        trace.saved = signature
