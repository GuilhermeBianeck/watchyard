import json

from watchyard.correlation import preview


def event(key, camera, start, *, end=None, label='person', point=None, colors=None, **extra):
    return {
        'id': key, 'camera': camera, 'camera_name': f'Camera {camera}', 'created': start,
        'first_seen': start, 'last_seen': start if end is None else end, 'label': label,
        'correlation_hint': json.dumps({'point': point, 'colors': colors}), **extra,
    }


def test_doorway_groups_returns_and_keeps_concurrent_people_separate():
    point = [.32, .71]
    groups = preview([
        event('first', 1, 10, end=22, point=point),
        event('second person', 1, 15, end=180, point=point),
        event('return', 1, 70, point=point),
        event('other part of view', 1, 80, point=[.8, .6]),
    ])
    assert [[e['id'] for e in g['events']] for g in groups] == [['first', 'return']]


def test_vehicles_use_movement_confirmation_and_disagreeing_plates_block_merge():
    groups = preview([
        event('vehicle', 3, 100, end=500, label='car', plate='AB-12-CD'),
        event('other view', 8, 103, label='car', plate='AB-12-CD'),
        event('another car', 5, 105, label='car', plate='AB-34-CD'),
    ])
    assert [e['id'] for e in groups[0]['events']] == ['vehicle', 'other view']
    assert groups[0]['events'][1]['reason'] == 'Matching plate across cameras'
    assert not preview([event('parked', 3, 100, end=500, label='car'),
                        event('later movement elsewhere', 8, 450, label='car')])


def test_relationship_is_learned_from_prior_independent_examples():
    color = [1.0] + [0.0]*15
    observations = []
    for i, stamp in enumerate((100, 600, 1100)):
        observations.extend([event(f'a{i}', 20, stamp, colors=color),
                             event(f'b{i}', 31, stamp+10, colors=color)])
    later = [event('later-a', 20, 1600, colors=color),
             event('later-b', 31, 1614, colors=color)]
    assert not any(g['id'] == 'later-a' for g in preview(observations[:4] + later))
    assert preview(observations + later)[0]['events'][1]['reason'].startswith('Recurring')
