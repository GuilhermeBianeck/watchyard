"""Advisory activity groups. This module never controls notification delivery."""
from collections import defaultdict
import json
import math

import cv2
import numpy as np

DOORWAY_GAP = 120
MAX_GROUP_AGE = 300
CROSS_CAMERA_WINDOW = 35
LABELS = {'person', 'car'}


def hint(frame, box):
    """Keep coarse colour and position, without storing another crop or face data."""
    height, width = frame.shape[:2]
    left, top, right, bottom = box
    # Torso or body area. Remove the top portion, which can contain a face.
    x1, x2 = int((left + .15 * (right-left))*width), int((right - .15 * (right-left))*width)
    y1, y2 = int((top + .28 * (bottom-top))*height), int((bottom - .23 * (bottom-top))*height)
    crop = frame[y1:y2, x1:x2]
    colors = None
    if min(crop.shape[:2]) >= 8:
        crop = cv2.resize(crop, (24, 24), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3)
        chromatic = (hsv[:, 1] >= 48) & (hsv[:, 2] >= 48)
        bins = np.where(chromatic, hsv[:, 0] // 15, 12 + hsv[:, 2] // 64)
        colors = (np.bincount(bins, minlength=16) / len(hsv)).round(4).tolist()
    return json.dumps({'point': [(left+right)/2, bottom], 'colors': colors})


def _prepare(row):
    result = dict(row)
    # Cars can be tracked while parked long before they first move.
    result['start'] = row['created'] if row['label'] == 'car' else (row.get('first_seen') or row['created'])
    result['last'] = row.get('last_seen') or row['created']
    result['hint'] = json.loads(row.get('correlation_hint') or '{}')
    return result


def _appearance(a, b):
    first, second = a['hint'].get('colors'), b['hint'].get('colors')
    if not first or not second:
        return 0
    # Grey or nearly black crops are common and weak evidence between views.
    if min(sum(first[:12]), sum(second[:12])) < .2:
        return 0
    return sum(min(x, y) for x, y in zip(first, second))


def _plate(a, b):
    if a['label'] != 'car' or not a.get('plate') or not b.get('plate'):
        return 0
    return 1 if a['plate'] == b['plate'] else -1


def _link(a, b):
    return a['label'], a['camera'], b['camera']


def _matches(a, b, patterns):
    if a['label'] != b['label'] or _plate(a, b) < 0:
        return None
    delta = b['start'] - a['start']
    if a['camera'] == b['camera']:
        # A moving vehicle event is anchored to motion onset, never parked presence.
        end = a['last'] if a['label'] == 'person' else a['start']
        limit = DOORWAY_GAP if a['label'] == 'person' else 18
        if not 0 <= b['start'] - end <= limit or delta <= 0:
            return None
        first, second = a['hint'].get('point'), b['hint'].get('point')
        if first and second:
            if math.dist(first, second) > .23:
                return None
            return (2, 'Repeated activity in the same area')
        return (1, 'Timing only on the same camera')

    if not 0 <= delta <= CROSS_CAMERA_WINDOW:
        return None
    if _plate(a, b) == 1:
        return (4, 'Matching plate across cameras')
    similarity = _appearance(a, b)
    learned = patterns.get(_link(a, b), [])
    if len(learned) >= 3 and similarity >= .66 and any(abs(delta-gap) <= 5 for _, gap in learned):
        return (3, 'Recurring camera transition with similar appearance')
    if delta <= 12 and similarity >= .76:
        return (2, 'Close timing and similar appearance across cameras')
    if delta <= 12:
        return (1, 'Timing only across cameras')
    return None


def preview(rows):
    events = sorted((_prepare(row) for row in rows if row['label'] in LABELS
                     and row.get('feedback') != 'false_alarm'), key=lambda e: (e['start'], e['id']))
    patterns = defaultdict(list)
    groups = []
    for event in events:
        candidates = []
        for group in reversed(groups):
            if event['start'] - group[0][0]['start'] > MAX_GROUP_AGE:
                break
            if any(_plate(previous, event) < 0 for previous, _ in group):
                continue
            if any(previous['camera'] == event['camera'] and previous['label'] == event['label']
                   and event['label'] == 'person' and previous['start'] <= event['start'] <= previous['last']
                   for previous, _ in group):
                continue
            matches = [(match, previous) for previous, _ in group
                       if (match := _matches(previous, event, patterns))]
            if matches:
                match, previous = max(matches, key=lambda pair: (pair[0][0], pair[1]['start']))
                candidates.append((match, previous, group))
        candidates.sort(key=lambda item: item[0][0], reverse=True)
        if not candidates or (len(candidates) > 1 and candidates[0][0][0] == candidates[1][0][0]):
            groups.append([(event, '')])
            continue
        (strength, reason), previous, group = candidates[0]
        group.append((event, reason))
        if previous['camera'] != event['camera'] and (
            strength == 4 or strength >= 2 and _appearance(previous, event) >= .82
        ):
            observations = patterns[_link(previous, event)]
            if not observations or event['start'] - observations[-1][0] >= DOORWAY_GAP:
                observations.append((event['start'], event['start'] - previous['start']))
    return [
        {'id': group[0][0]['id'], 'label': group[0][0]['label'],
         'events': [{'id': event['id'], 'camera_name': event['camera_name'],
                     'created': event['created'], 'reason': reason} for event, reason in group]}
        for group in reversed(groups) if len(group) > 1
    ][:12]
