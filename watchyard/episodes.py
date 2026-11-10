"""Connect nearby activity groups without treating their tracks as one object."""
import math

from .correlation import _prepare, last_point

MAX_EPISODE_SECONDS = 600
PERSON_WINDOW = 45
MOTION_WINDOW = 25
NEARBY = .20


def _nearby(a, b):
    # Footprints from different views are in different coordinate systems.
    if a['camera'] != b['camera']:
        return False
    points_a = (a['hint'].get('point'), a['hint'].get('entry'), last_point(a))
    points_b = (b['hint'].get('point'), b['hint'].get('entry'), last_point(b))
    return any(math.dist(x, y) <= NEARBY for x in points_a if x for y in points_b if y)


def related_episode(event, history):
    current = _prepare(event)
    matches = set()
    vehicle_groups = {
        (row['episode_id'], row['activity_group']) for row in history if row['label'] == 'car'
    }
    for row in history:
        previous = _prepare(row)
        if not _nearby(previous, current):
            continue
        if current['label'] == previous['label']:
            # Co-visible people can be part of one scene while their tracks and
            # individual recordings stay separate. Cars retain separate groups.
            if current['label'] == 'person' and abs(current['created'] - previous['created']) <= PERSON_WINDOW:
                if max(current['start'], previous['start']) < min(current['last'], previous['last']):
                    matches.add(previous['episode_id'])
            continue
        car, person = (current, previous) if current['label'] == 'car' else (previous, current)
        motion = car.get('last_motion') or car['created']
        if person['start'] - MOTION_WINDOW <= motion <= person['last'] + MOTION_WINDOW:
            if not any(episode == previous['episode_id'] and group != car['activity_group']
                       for episode, group in vehicle_groups):
                matches.add(previous['episode_id'])
    return next(iter(matches)) if len(matches) == 1 else None
