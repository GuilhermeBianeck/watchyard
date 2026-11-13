"""Local, face-free evidence for a person retracing a path in the same view."""
import json
import math

import cv2
import numpy as np

RETURN_GAP = 120
RETURN_WINDOW = 600
SAMPLE_SPACING = .035
MAX_SAMPLES = 12


def sample_person(frame, box, elapsed):
    height, width = frame.shape[:2]
    left, top, right, bottom = box
    w, h = right - left, bottom - top
    bands = []
    # Sample the upper body and legs independently, excluding the head.
    for start, end in ((.22, .48), (.56, .81)):
        crop = frame[int((top + start*h)*height):int((top + end*h)*height),
                     int((left + .25*w)*width):int((right - .25*w)*width)]
        if min(crop.shape[:2]) < 6:
            return None
        hsv = cv2.cvtColor(cv2.resize(crop, (24, 24), interpolation=cv2.INTER_AREA),
                           cv2.COLOR_BGR2HSV).reshape(-1, 3)
        chromatic = (hsv[:, 1] >= 45) & (hsv[:, 2] >= 40)
        bins = np.where(chromatic, hsv[:, 0] // 15, 12 + hsv[:, 2] // 43)
        bands.append((np.bincount(bins, minlength=18) / len(hsv)).round(3).tolist())
    return [[(left + right) / 2, bottom], h, *bands, round(elapsed, 2)]


def add_sample(samples, sample):
    if sample is None:
        return
    if samples and math.dist(samples[-1][0], sample[0]) < SAMPLE_SPACING:
        samples[-1] = sample
        return
    samples.append(sample)
    if len(samples) > MAX_SAMPLES:
        del samples[1]


def _agreement(a, b):
    point_a, height_a, torso_a, legs_a, _ = a
    point_b, height_b, torso_b, legs_b, _ = b
    if math.dist(point_a, point_b) > .115 or min(height_a, height_b) < .67 * max(height_a, height_b):
        return False
    return all(sum(min(x, y) for x, y in zip(first, second)) >= .72
               for first, second in ((torso_a, torso_b), (legs_a, legs_b)))


def _retraces(previous, current):
    # Compare the end of the prior path with the beginning of the return.
    # Two distinct positions must agree in reverse order. Repeated frames
    # at the doorway alone cannot link two events.
    if not previous or not current or math.dist(previous[-1][0], current[0][0]) > .13:
        return False
    previous = [sample for sample in previous[-8:] if previous[-1][-1] - sample[-1] <= 20]
    current = [sample for sample in current[:8] if sample[-1] - current[0][-1] <= 8]
    pairs = [(i, j) for i, a in enumerate(previous) for j, b in enumerate(current)
             if _agreement(a, b)]
    for i, j in pairs:
        for k, m in pairs:
            if i <= k or j >= m:
                continue
            old = [end - start for start, end in zip(previous[k][0], previous[i][0])]
            new = [end - start for start, end in zip(current[j][0], current[m][0])]
            lengths = math.hypot(*old), math.hypot(*new)
            if min(lengths) >= .06 and sum(x*y for x, y in zip(old, new)) <= -.7 * math.prod(lengths):
                return True
    return False


def retraced_person_group(event, history):
    """Require one plausible prior group in the same view."""
    path = json.loads(event.get('person_path') or '[]')
    if len(path) < 2:
        return None
    start = event.get('first_seen') or event['created']
    same_view = [row for row in history if row['label'] == 'person'
                 and row['camera'] == event['camera'] and row['id'] != event['id']
                 and row.get('feedback') != 'false_alarm']
    # A competing person can enter as the current track is being confirmed.
    if any((row.get('first_seen') or row['created']) <= (event.get('last_seen') or event['created'])
           and (row.get('last_seen') or row['created']) >= start for row in same_view):
        return None
    anchors = {row['id']: row for row in history}
    groups = set()
    for row in same_view:
        group = row.get('activity_group')
        if not group or not 0 < start - (row.get('last_seen') or row['created']) <= RETURN_GAP:
            continue
        anchor = anchors.get(group)
        if not anchor or anchor.get('feedback') == 'false_alarm' or event['created'] - anchor['created'] > RETURN_WINDOW:
            continue
        if _retraces(json.loads(row.get('person_path') or '[]'), path):
            groups.add(group)
    return next(iter(groups)) if len(groups) == 1 else None
