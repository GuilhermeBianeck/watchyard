"""Display-only persistence. Alert tracking consumes raw detections."""
from .rules import iou


class Overlays:
    HOLD_SECONDS = 4

    def __init__(self):
        self.entries = []

    def update(self, detections, now):
        previous = [(d, seen) for d, seen in self.entries if now-seen < self.HOLD_SECONDS]
        for detection in detections:
            scores = [iou(d['box'], detection['box']) if d['label'] == detection['label']
                      else 0 for d, _ in previous]
            if scores and max(scores) >= .25:
                previous.pop(scores.index(max(scores)))
        self.entries = [(d, now) for d in detections] + previous

    def visible(self, now, labels):
        return [d for d, seen in self.entries
                if now-seen < self.HOLD_SECONDS and d['label'] in labels]
