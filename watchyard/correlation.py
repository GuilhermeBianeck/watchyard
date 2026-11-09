"""Activity grouping shared by the dashboard and Telegram delivery."""
from collections import defaultdict
import json
import math

import cv2
import numpy as np

from .rules import iou

DOORWAY_GAP = 120
MAX_GROUP_AGE = 300
MAX_PERSON_GROUP_AGE = 600
CLOSE_TRANSITION = 12
LABELS = {'person', 'car'}


def footprint(box):
    left, _, right, bottom = box
    return ((left + right) / 2, bottom)


def hint(frame, box, entry_box=None):
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
    return json.dumps({'point': footprint(box), 'entry': footprint(entry_box or box),
                       'box': box, 'colors': colors})


def _prepare(row):
    result = dict(row)
    # Cars can be tracked while parked long before they first move.
    result['start'] = row['created'] if row['label'] == 'car' else (row.get('first_seen') or row['created'])
    result['last'] = row.get('last_seen') or row['created']
    result['hint'] = json.loads(row.get('correlation_hint') or '{}')
    return result


def _colors(event):
    # Grey or nearly black crops are common and weak evidence between views.
    colors = event['hint'].get('colors')
    return colors if colors and sum(colors[:12]) >= .2 else None


def _appearance(a, b):
    first, second = _colors(a), _colors(b)
    return sum(min(x, y) for x, y in zip(first, second)) if first and second else 0


def _color_conflict(a, b, similarity):
    first, second = _colors(a), _colors(b)
    if not first or not second:
        return False
    if similarity < .35:
        return True
    first_total, second_total = sum(first[:12]), sum(second[:12])
    return min(first_total, second_total) >= .30 and sum(
        min(x / first_total, y / second_total) for x, y in zip(first[:12], second[:12])
    ) < .32


def _plate(a, b):
    if a['label'] != 'car' or not a.get('plate') or not b.get('plate'):
        return 0
    return 1 if a['plate'] == b['plate'] else -1


def _link(a, b):
    return a['label'], a['camera'], b['camera']


def _area_distance(a, b):
    last = (a['last_x'], a['last_y']) if a.get('last_x') is not None and a.get('last_y') is not None else None
    ends = (a['hint'].get('point'), last)
    starts = (b['hint'].get('point'), b['hint'].get('entry'))
    return min((math.dist(end, start) for end in ends if end for start in starts if start), default=None)


def _overlap(a, b):
    return max(a['start'], b['start']) <= min(a['last'], b['last'])


def _track_fragment(a, b):
    # Only a brief overlap of nearly identical detections can be a split track.
    # Tight framing plus colour keeps two people side by side from being merged.
    if not 0 <= a['last'] - b['start'] <= 2.5 or b['start'] - a['start'] < 1:
        return False
    first, second = a['hint'].get('point'), b['hint'].get('point')
    if not first or not second or math.dist(first, second) > .035 or _appearance(a, b) < .76:
        return False
    first_box, second_box = a['hint'].get('box'), b['hint'].get('box')
    return not (first_box and second_box) or iou(first_box, second_box) >= .7


def _same_camera(a, b, similarity, plate, disagree):
    delta = b['start'] - a['start']
    if delta <= 0:
        return None
    distance = _area_distance(a, b)
    if a['label'] == 'car':
        # Compare movement onsets. A parked car can stay tracked for hours.
        if plate == 1 and delta <= DOORWAY_GAP:
            return 4, 'Matching plate during repeated movement'
        if not disagree and delta <= 18 and (distance is None or distance <= .23):
            return 2 if distance is not None else 1, 'Repeated vehicle movement nearby'
        if distance is not None and distance <= .12 and delta <= DOORWAY_GAP and similarity >= .78:
            return 3, 'Similar vehicle moving again in the same area'
        return None
    gap = b['start'] - a['last']
    if gap <= 0:
        return (3, 'Brief split of the same detection') if _track_fragment(a, b) else None
    # On the same view a close return to the same spot helps when a change
    # of pose or lighting shifts the colour histogram.
    nearby_return = distance is not None and distance <= .10 and similarity >= .35
    if disagree and not nearby_return:
        return None
    if distance is None:
        return (1, 'Timing only on the same camera') if gap <= DOORWAY_GAP else None
    if gap <= 20 and distance <= .38 and similarity >= .55:
        return 3, 'Similar appearance after a short tracking gap'
    if gap <= 35 and distance <= .38 and similarity >= .65:
        return 3, 'Similar appearance after a short tracking gap'
    if gap <= 180 and ((distance <= .18 and similarity >= .74) or (distance <= .08 and similarity >= .62)):
        return 3, 'Similar appearance on return to the same area'
    if gap <= DOORWAY_GAP and distance <= .23:
        return 2, 'Repeated activity in the same area'
    return None


def _on_learned_route(a, b, patterns):
    first, second = a['hint'].get('point'), b['hint'].get('point')
    if not first or not second:
        return False
    forward = patterns.get(_link(a, b), ())
    reverse = patterns.get(_link(b, a), ())
    examples = sorted(
        list(forward) + [(stamp, delay, end, start) for stamp, delay, start, end in reverse],
        key=lambda example: example[0],
    )
    independent = []
    for stamp, _, start, end in examples:
        if start and end and (not independent or stamp - independent[-1][0] >= DOORWAY_GAP):
            independent.append((stamp, start, end))
    return len(independent) >= 3 and sum(
        math.dist(first, start) <= .30 and math.dist(second, end) <= .30
        for _, start, end in independent
    ) >= 2


def _matches(a, b, patterns):
    if a['label'] != b['label']:
        return None
    if a['start'] > b['start']:
        a, b = b, a
    plate = _plate(a, b)
    if plate < 0:
        return None
    similarity = _appearance(a, b)
    disagree = _color_conflict(a, b, similarity)
    if a['camera'] == b['camera']:
        return _same_camera(a, b, similarity, plate, disagree)
    delta = b['start'] - a['start']
    if plate == 1 and delta <= 90:
        return 4, 'Matching plate across cameras'
    if disagree:
        return None
    if delta <= 35:
        learned = patterns.get(_link(a, b), ())
        if len(learned) >= 3 and similarity >= .66 and any(abs(delta-gap) <= 5 for _, gap, _, _ in learned):
            return 3, 'Recurring camera transition with similar appearance'
        if similarity >= .68 and (delta <= CLOSE_TRANSITION or (a['hint'].get('point') and b['hint'].get('point'))):
            return 2, 'Close timing and similar appearance across cameras'
    if a['label'] == 'car':
        if delta <= 65 and _on_learned_route(a, b, patterns):
            return 3, 'Repeated vehicle route across cameras'
    else:
        tail = max(0, b['start'] - a['last'])
        if 35 < delta <= 75 and tail <= 20 and similarity >= .72:
            return 3, 'Similar appearance near the end of another camera view'
        plausible_route = (tail <= 90 and similarity >= .50) or (tail <= 120 and similarity >= .82)
        if delta <= 150 and plausible_route and _on_learned_route(a, b, patterns):
            return 3, 'Repeated person route with similar appearance'
    if delta <= CLOSE_TRANSITION:
        return 1, 'Timing only across cameras'
    return None


def _learn(patterns, previous, event):
    if previous['camera'] == event['camera']:
        return
    if previous['start'] > event['start']:
        previous, event = event, previous
    delta = event['start'] - previous['start']
    plate = _plate(previous, event)
    limit, minimum = (CLOSE_TRANSITION, .50) if event['label'] == 'car' else (35, .76)
    if plate < 0 or delta > 90 or (plate != 1 and (delta > limit or _appearance(previous, event) < minimum)):
        return
    observations = patterns[_link(previous, event)]
    if not observations or event['start'] - observations[-1][0] >= DOORWAY_GAP:
        observations.append((event['start'], delta, previous['hint'].get('point'), event['hint'].get('point')))


def preview(rows, *, limit=12, include_single=False):
    # Reproduce delivery order even when a later-confirmed track started first.
    events = sorted((_prepare(row) for row in rows if row['label'] in LABELS
                     and row.get('feedback') != 'false_alarm'), key=lambda e: (e['created'], e['id']))
    patterns = defaultdict(list)
    groups = []
    group_keys = {}
    for event in events:
        assigned = event.get('activity_group') or (event['id'] if event['id'] in group_keys else None)
        if assigned:
            group = group_keys.get(assigned)
            if group is None:
                group = []
                groups.append(group)
                group_keys[assigned] = group
            for previous, _ in reversed(group):
                _learn(patterns, previous, event)
            group.append((event, event.get('activity_reason') or ''))
            continue
        candidates = []
        limit_age = MAX_PERSON_GROUP_AGE if event['label'] == 'person' else MAX_GROUP_AGE
        for group in reversed(groups):
            age = event['created'] - group[0][0]['created']
            if age > limit_age:
                break
            if group[0][0]['label'] != event['label']:
                continue
            if any(_plate(previous, event) < 0 for previous, _ in group):
                continue
            if any(previous['camera'] == event['camera'] and previous['label'] == event['label']
                   and _overlap(previous, event)
                   and not _track_fragment(*sorted((previous, event), key=lambda e: e['start']))
                   for previous, _ in group):
                continue
            matches = [(match, previous) for previous, _ in group
                       if (match := _matches(previous, event, patterns))
                       and (age <= MAX_GROUP_AGE or match[0] >= 3)]
            if matches:
                match, previous = max(matches, key=lambda pair: (pair[0][0], pair[1]['start']))
                candidates.append((match, previous, group))
        candidates.sort(key=lambda item: item[0][0], reverse=True)
        if not candidates or (len(candidates) > 1 and candidates[0][0][0] == candidates[1][0][0]):
            group = [(event, '')]
            groups.append(group)
            group_keys[event['id']] = group
            continue
        (_, reason), previous, group = candidates[0]
        _learn(patterns, previous, event)
        group.append((event, reason))
    return [
        {'id': key, 'label': group[0][0]['label'],
         'events': [{'id': event['id'], 'camera_name': event['camera_name'],
                     'created': event['created'], 'reason': reason} for event, reason in group]}
        for key, group in reversed(group_keys.items()) if include_single or len(group) > 1
    ][:limit]
