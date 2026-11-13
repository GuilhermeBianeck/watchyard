"""Small multi-object tracker and deterministic notification rules."""
import math
from dataclasses import dataclass, field

import cv2
from numpy import ndarray

from .motion import vehicle_motion
from .person_path import add_sample, sample_person

VEHICLE_GAP = 5


def inside(point, polygon):
    if not polygon:
        return True
    x, y = point
    result = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj-xi) * (y-yi) / (yj-yi) + xi:
            result = not result
        j = i
    return result


def center(box):
    return ((box[0]+box[2])/2, (box[1]+box[3])/2)


def iou(a, b):
    w = max(0, min(a[2], b[2])-max(a[0], b[0]))
    h = max(0, min(a[3], b[3])-max(a[1], b[1]))
    intersection = w*h
    union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union else 0


def ignored_box(label, box, camera):
    """Ignore a recurring false detection only at a matching location and size."""
    return any(iou(box, reference) >= 0.55
               for reference in camera.get('ignore_boxes', {}).get(label, ()))


def family(label):
    return "animal" if label in ("cat", "dog") else label


@dataclass
class Track:
    id: int
    label: str
    box: list
    origin: tuple
    first: float
    last: float
    observations: list = field(default_factory=list)
    alerted: bool = False
    displacement: float = 0
    event_id: str | None = None
    first_box: list = field(default_factory=list)
    moved_at: float | None = None
    sampled_at: float | None = None
    initial_colors: list | None = None
    heading: tuple | None = None
    vehicle_frame: ndarray | None = field(default=None, repr=False, compare=False)
    person_path: list = field(default_factory=list, repr=False)
    last_strong: float | None = None


class Tracker:
    def __init__(self):
        self.tracks = {}
        self.counter = 0

    def update(self, detections, now, zone, confirmation=3, window=3, *, frame=None, weak_people=()):
        self.tracks = {k:t for k,t in self.tracks.items() if now-t.last < 8}
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame is not None and any(
            d['label'] == 'car' for d in detections
        ) else None
        matched = set()
        events = []
        # Match globally by spatial proximity, rather than detection order.
        candidates = []
        for i, d in enumerate(detections):
            for key, t in self.tracks.items():
                if family(d['label']) != family(t.label):
                    continue
                distance = math.dist(center(d['box']), center(t.box))
                overlap = iou(d['box'], t.box)
                if distance < 0.13 or overlap > 0.15:
                    candidates.append((distance-overlap*0.3, i, key))
        assignments = {}
        for _, i, key in sorted(candidates):
            if i not in assignments and key not in matched:
                assignments[i] = key
                matched.add(key)
        continued = self.vehicle_continuations(detections, now, gray, assignments, matched)
        assignments.update(continued)
        weak = len(detections)
        detections = [*detections, *weak_people]
        weak_matches = {}
        for i in range(weak, len(detections)):
            box = detections[i]['box']
            if any(d['label'] == 'person' and iou(d['box'], box) >= .35 for d in detections[:weak]):
                continue
            # A low-scoring box can maintain a confirmed track when it closely
            # overlaps the last position. It cannot start or confirm a track.
            possible = [key for key, track in self.tracks.items() if key not in matched
                        and track.label == 'person' and track.event_id and track.last_strong is not None
                        and now - track.last <= 2.5 and now - track.last_strong <= 3
                        and iou(track.box, box) >= .35]
            if len(possible) == 1:
                weak_matches.setdefault(possible[0], []).append(i)
        assignments.update({indices[0]: key for key, indices in weak_matches.items() if len(indices) == 1})
        confirmed_tracks = []
        for i, d in enumerate(detections):
            if i >= weak and i not in assignments:
                continue
            box = d['box']
            foot = ((box[0]+box[2])/2, box[3])
            if i in assignments:
                t = self.tracks[assignments[i]]
                if t.label == 'car' and gray is not None and t.vehicle_frame is not None:
                    if i in continued or (now - t.last <= VEHICLE_GAP and
                                          vehicle_motion(t.vehicle_frame, gray, t.box, box)):
                        t.moved_at = now
                if t.label == 'person':
                    t.heading = (foot[0] - (t.box[0]+t.box[2])/2, foot[1] - t.box[3]) if now-t.last <= 2.5 else None
            else:
                self.counter += 1
                t = Track(self.counter, d['label'], box, center(box), now, now, first_box=box)
                self.tracks[t.id] = t
            t.last, t.box, t.label = now, box, d['label']
            if i < weak:
                t.last_strong = now
            if t.label == 'car':
                t.vehicle_frame = gray
            in_zone = inside(foot, zone)
            if t.label == 'person' and frame is not None and in_zone:
                add_sample(t.person_path, sample_person(frame, box, now - t.first))
            # Require repeated observations INSIDE the alert zone.
            t.observations = [v for v in t.observations if now-v[0] < window]
            if in_zone and i < weak:
                t.observations.append((now, d['confidence']))
            elif not in_zone:
                t.observations.clear()
            t.displacement = max(t.displacement, math.dist(t.origin, center(box)))
            confirmed = len(t.observations) >= confirmation
            moving = t.label != 'car' or (
                t.displacement >= .035 and t.moved_at is not None and now - t.moved_at <= window
            )
            if confirmed and moving and not t.alerted:
                confirmed_tracks.append((t, d))

        for track, detection in confirmed_tracks:
            previous = self.recent_predecessor(track) if track.label != 'car' else None
            track.alerted = True
            if previous:
                # Continue the existing event so its replay includes the later observations.
                track.event_id = previous.event_id
                del self.tracks[previous.id]
            else:
                events.append({**detection, 'track_id': track.id})
        return events

    def vehicle_continuations(self, detections, now, gray, assignments, matched):
        # An approaching car can jump outside the ordinary tracker radius.
        # Reconnect only with a unique patch match to a recently moving car.
        if gray is None:
            return {}
        candidates = {}
        for key, track in self.tracks.items():
            if key in matched or track.vehicle_frame is None or track.moved_at is None:
                continue
            if now - track.moved_at > VEHICLE_GAP:
                continue
            for i, detection in enumerate(detections):
                if i not in assignments and detection['label'] == 'car' and vehicle_motion(
                    track.vehicle_frame, gray, track.box, detection['box']
                ):
                    candidates.setdefault(i, []).append(key)
        return {
            i: keys[0] for i, keys in candidates.items()
            if len(keys) == 1 and sum(keys[0] in others for others in candidates.values()) == 1
        }

    def recent_predecessor(self, track):
        # Only stitch sequential tracks. Two people visible at once remain distinct.
        candidates = [
            previous for previous in self.tracks.values()
            if previous.alerted
            and previous.label == track.label
            and 0 < track.first - previous.last <= 3
            and math.dist(center(previous.box), center(track.first_box)) <= 0.23
        ]
        return min(candidates, key=lambda previous: math.dist(center(previous.box), center(track.first_box)),
                   default=None)
