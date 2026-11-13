"""Connect nearby activity groups without treating their tracks as one object."""
import json
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


def _at_vehicle(car, person):
    if car['camera'] != person['camera'] or car.get('last_motion') is None:
        return False
    if not 0 <= car['start'] - person['last'] <= 20 or abs(car['last_motion'] - car['start']) > 20:
        return False
    box = car['hint'].get('box')
    if not box:
        return False
    left, top, right, bottom = box
    path = json.loads(person.get('person_path') or '[]')
    # Require the last two positions at the vehicle, close together in time.
    return (len(path) >= 2 and path[-1][-1] - path[-2][-1] <= 6
            and all(left <= x <= right and top <= y <= bottom for (x, y), *_ in path[-2:]))


def related_episode(event, history):
    current = _prepare(event)
    matches = set()
    vehicle_groups = {
        (row['episode_id'], row['activity_group']) for row in history if row['label'] == 'car'
    }
    for row in history:
        previous = _prepare(row)
        if current['label'] == previous['label']:
            # Co-visible people can be part of one scene while their tracks and
            # individual recordings stay separate. Cars retain separate groups.
            if (current['label'] == 'person' and abs(current['created'] - previous['created']) <= PERSON_WINDOW
                    and _nearby(previous, current)):
                if max(current['start'], previous['start']) < min(current['last'], previous['last']):
                    matches.add(previous['episode_id'])
            continue
        car, person = (current, previous) if current['label'] == 'car' else (previous, current)
        motion = car.get('last_motion') or car['created']
        nearby_motion = (person['start'] - MOTION_WINDOW <= motion <= person['last'] + MOTION_WINDOW
                         and _nearby(car, person))
        if nearby_motion or _at_vehicle(car, person):
            if not any(episode == previous['episode_id'] and group != car['activity_group']
                       for episode, group in vehicle_groups):
                matches.add(previous['episode_id'])
    return next(iter(matches)) if len(matches) == 1 else None
