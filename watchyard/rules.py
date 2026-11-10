"""Small multi-object tracker and deterministic notification rules."""
import math
from dataclasses import dataclass, field


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


class Tracker:
    def __init__(self):
        self.tracks = {}
        self.counter = 0

    def update(self, detections, now, zone, confirmation=3, window=3):
        self.tracks = {k:t for k,t in self.tracks.items() if now-t.last < 8}
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
        confirmed_tracks = []
        for i, d in enumerate(detections):
            box = d['box']
            foot = ((box[0]+box[2])/2, box[3])
            if i in assignments:
                t = self.tracks[assignments[i]]
                if t.label == 'car' and math.dist(center(t.box), center(box)) >= .02:
                    t.moved_at = now
                if t.label == 'person':
                    t.heading = (foot[0] - (t.box[0]+t.box[2])/2, foot[1] - t.box[3]) if now-t.last <= 2.5 else None
            else:
                self.counter += 1
                t = Track(self.counter, d['label'], box, center(box), now, now, first_box=box)
                self.tracks[t.id] = t
            t.last, t.box, t.label = now, box, d['label']
            in_zone = inside(foot, zone)
            # Require repeated observations INSIDE the alert zone.
            t.observations = [v for v in t.observations if now-v[0] < window]
            if in_zone:
                t.observations.append((now, d['confidence']))
            else:
                t.observations.clear()
            t.displacement = max(t.displacement, math.dist(t.origin, center(box)))
            confirmed = len(t.observations) >= confirmation
            moving = t.label != 'car' or t.displacement >= 0.035
            if confirmed and moving and not t.alerted:
                confirmed_tracks.append((t, d))

        for track, detection in confirmed_tracks:
            previous = self.recent_predecessor(track)
            track.alerted = True
            if previous:
                # Continue the existing event so its replay includes the later observations.
                track.event_id = previous.event_id
                del self.tracks[previous.id]
            else:
                events.append({**detection, 'track_id': track.id})
        return events

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
