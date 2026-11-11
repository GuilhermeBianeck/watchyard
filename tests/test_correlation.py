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


def test_group_delivers_once_per_telegram_account_and_allows_failed_first_send(tmp_path):
    import time

    from watchyard.config import Settings
    from watchyard.service import Service

    settings = Settings(tmp_path)
    settings.save_secrets({'TELEGRAM_CHAT_ID': 123})
    service = Service(settings)
    members = service.telegram.members
    invite = members.invite('telegram', 'Second account', 'viewer')
    members.accept(invite['code'], 'telegram', '456', client='tg')
    (tmp_path/'events'/'vehicle.jpg').write_bytes(b'image')
    first = service.store.add({'id': 1, 'name': 'First view'}, 'car', .9, 'vehicle.jpg')
    second = service.store.add({'id': 3, 'name': 'Second view'}, 'car', .9, 'vehicle.jpg')
    now = time.time()
    service.store.db.execute('UPDATE events SET created=? WHERE id=?', (now-8, first))
    service.store.db.execute('UPDATE events SET created=? WHERE id=?', (now-5, second))
    service.store.db.commit()
    calls = []

    def photo(*args, event_id, chat_id, **kwargs):
        calls.append((event_id, str(chat_id)))
        if event_id == first and str(chat_id) == '456':
            raise RuntimeError('unavailable')

    service.telegram.photo = photo
    service.notifications.deliver_once(service.store)
    assert sorted(calls) == sorted([(first, '123'), (first, '456'), (second, '456')])
    assert service.store.event(first)['activity_group'] == service.store.event(second)['activity_group']
    assert [r['status'] for r in service.store.recipient_deliveries(second)].count('grouped') == 1

    service.store.db.execute('UPDATE events SET next_try=0 WHERE id=?', (first,))
    service.store.db.execute('UPDATE recipient_deliveries SET next_try=0 WHERE event_id=?', (first,))
    service.store.db.commit()
    service.notifications.deliver_once(service.store)
    assert len(calls) == 3

    third = service.store.add({'id': 4, 'name': 'Third view'}, 'car', .9, 'vehicle.jpg')
    service.notifications.deliver_once(service.store)
    assert len(calls) == 3
    assert service.store.event(third)['status'] == 'grouped'


def test_confirmation_order_respects_an_existing_group_even_when_second_track_started_first():
    color = [1.0] + [0.0]*15
    known = event('delivered', 6, 109, end=111, point=[.4, .7], colors=color, activity_group='delivered')
    next_view = event('confirmed later', 12, 100, end=114, point=[.6, .8], colors=color)
    next_view['created'] = 114
    [group] = preview([next_view, known])
    assert group['id'] == 'delivered'
    assert [item['id'] for item in group['events']] == ['delivered', 'confirmed later']


def test_matches_person_across_a_longer_transition_with_color_but_keeps_different_people_apart():
    blue = [1.0] + [0.0]*15
    green = [0.0, 1.0] + [0.0]*14
    origin = event('first', 5, 100, end=124, point=[.2, .7], colors=blue)
    same_person = event('same', 9, 113, point=[.8, .4], colors=blue)
    other_person = event('other', 10, 115, point=[.5, .5], colors=green)
    [group] = preview([origin, same_person, other_person])
    assert [item['id'] for item in group['events']] == ['first', 'same']
    # With no corroboration, the longer window does not group based on timing.
    assert not preview([origin, event('unknown', 9, 114, point=[.8, .4])])


def test_handoff_uses_end_position_and_fragment_must_have_nearly_identical_boxes():
    blue = [1.0] + [0.0]*15
    walking = event('first', 5, 100, end=129, point=[.2, .7], colors=blue, last_x=.7, last_y=.8)
    returned = event('return', 5, 175, point=[.7, .8], colors=blue)
    assert preview([walking, returned])[0]['id'] == 'first'

    first = event('first', 5, 100, end=110.3, point=[.35, .7], colors=blue)
    fragment = event('fragment', 5, 108, end=115, point=[.36, .7], colors=blue)
    for record, box in [(first, [.3, .4, .4, .7]), (fragment, [.31, .4, .41, .7])]:
        hint = json.loads(record['correlation_hint'])
        record['correlation_hint'] = json.dumps({**hint, 'box': box})
    assert preview([first, fragment])[0]['id'] == 'first'
    hint = json.loads(fragment['correlation_hint'])
    fragment['correlation_hint'] = json.dumps({**hint, 'box': [.26, .2, .46, .7]})
    assert not preview([first, fragment])


def test_vehicle_route_learns_from_separate_corroborated_trips_and_accepts_ir_views():
    blue = [1.0] + [0.0]*15
    infrared = [0.0]*15 + [1.0]
    points = [.4, .43], [.3, .8]
    confirmed = []
    for i, stamp in enumerate((100, 500, 900)):
        confirmed.extend([
            event(f'a{i}', 24, stamp, label='car', point=points[0], colors=blue),
            event(f'b{i}', 91, stamp+5, label='car', point=points[1], colors=blue),
        ])
    vehicle = event('night', 24, 1500, label='car', point=[.46, .49], colors=infrared, plate='AB-12-CD')
    later = event('night second view', 91, 1533, label='car', point=[.31, .96], colors=infrared)
    assert all(g['id'] != 'night' for g in preview(confirmed[:4] + [vehicle, later]))
    [group] = preview(confirmed + [vehicle, later], limit=1)
    assert group['id'] == 'night'
    assert group['events'][-1]['reason'] == 'Repeated vehicle route across cameras'
    later['plate'] = 'XY-12-ZZ'
    assert all(g['id'] != 'night' for g in preview(confirmed + [vehicle, later]))
    later['plate'] = None
    later['correlation_hint'] = json.dumps({'point': [.88, .32], 'colors': infrared})
    assert all(g['id'] != 'night' for g in preview(confirmed + [vehicle, later]))


def test_multiple_equally_plausible_matches_stay_separate():
    color = [1.0] + [0.0]*15
    rows = [
        event('one', 2, 100, end=115, colors=color, point=[.4, .6]),
        event('two', 2, 103, end=117, colors=color, point=[.5, .7]),
        event('ambiguous', 9, 114, colors=color, point=[.3, .6]),
    ]
    assert not preview(rows)


def test_reappearance_after_a_blind_gap_stays_separate_even_with_the_same_clothing():
    color = [1.0] + [0.0]*15
    first = event('first', 2, 100, end=110, point=[.4, .6], colors=color, recent_colors=json.dumps(color))
    visitor = event('visitor', 2, 185, point=[.4, .6], colors=color, recent_colors=json.dumps(color))
    assert not preview([first, visitor])


def _trajectory(key, camera, start, end, *, entry, point, exit_point):
    color = [.9, .1] + [0.0]*14
    row = event(key, camera, start, end=end, point=point, colors=color, recent_colors=json.dumps(color),
                last_x=exit_point[0], last_y=exit_point[1])
    row['correlation_hint'] = json.dumps({'point': point, 'entry': entry, 'colors': color})
    return row


def test_long_group_follows_observed_direction_and_rejects_opposite_traffic():
    first = _trajectory('continuous', 2, 100, 750, entry=[.2,.6], point=[.3,.6], exit_point=[.46,.6])
    first['exit_vector'] = json.dumps([.03, 0])
    handoff = _trajectory('continues', 2, 754, 760, entry=[.47,.6], point=[.54,.6], exit_point=[.61,.6])
    assert [row['id'] for row in preview([first, handoff])[0]['events']] == ['continuous', 'continues']
    opposite = _trajectory('incoming', 2, 754, 760, entry=[.47,.6], point=[.39,.6], exit_point=[.35,.6])
    assert not preview([first, opposite])
    missing_direction = {**first, 'exit_vector': None}
    assert not preview([missing_direction, handoff])
    competitor = {**_trajectory('other', 9, 745, 751, entry=[.2,.6], point=[.3,.6], exit_point=[.4,.6]),
                  'activity_group': 'other'}
    assert not preview([first, competitor, handoff])
    handoff.pop('recent_colors')
    assert not preview([first, handoff])


def test_long_cross_camera_group_requires_repeated_directional_routes_and_matching_samples():
    training = []
    for stamp in (100, 2600, 5100):
        training.extend([
            _trajectory(f'leave-{stamp}', 4, stamp, stamp+20, entry=[.2,.5], point=[.25,.5], exit_point=[.3,.5]),
            _trajectory(f'enter-{stamp}', 9, stamp+29, stamp+39, entry=[.55,.65], point=[.6,.65], exit_point=[.65,.65]),
        ])
    first = _trajectory('long visit', 4, 8000, 8680, entry=[.2,.5], point=[.25,.5], exit_point=[.3,.5])
    continuation = _trajectory('next view', 9, 8689, 8700, entry=[.55,.65], point=[.6,.65], exit_point=[.65,.65])
    assert preview(training+[first, continuation])[0]['id'] == 'long visit'
    assert all(group['id'] != 'long visit' for group in preview(training[:4]+[first, continuation]))
    other_entry = _trajectory('different entrance', 9, 8689, 8700, entry=[.85,.95], point=[.6,.65], exit_point=[.65,.65])
    assert all(group['id'] != 'long visit' for group in preview(training+[first, other_entry]))


def test_long_vehicle_group_requires_recent_movement_and_the_same_plate():
    first = event('vehicle', 1, 100, end=550, label='car', plate='AB-12-CD', last_motion=545)
    target = event('other view', 2, 557, label='car', plate='AB-12-CD')
    assert preview([first, target])[0]['id'] == 'vehicle'
    first['last_motion'] = 103
    assert not preview([first, target])
    first['last_motion'] = 545
    target['plate'] = 'XY-34-ZZ'
    assert not preview([first, target])


def test_shadow_handoff_uses_a_colour_signal_and_a_short_ordered_gap():
    blue_in_shadow = [0.0]*6 + [.12, 0, 0, 0, 0, .01, .87, 0, 0, 0]
    blue_in_light = [0.0]*6 + [.33, .31, .01, 0, .01, 0, .19, .12, .03, 0]
    start = event('doorway', 17, 100, end=110, colors=blue_in_shadow, point=[.36, .54])
    target = event('outdoors', 24, 120, colors=blue_in_light, point=[.12, .60])
    assert preview([start, target])[0]['events'][-1]['reason'].startswith('Short handoff')
    late = event('late', 24, 128, colors=blue_in_light, point=[.12, .60])
    assert not preview([start, late])
    black = [0.0]*12 + [1, 0, 0, 0]
    achromatic = event('no colour', 17, 100, end=110, colors=black, point=[.36, .54])
    assert not preview([achromatic, target])


def test_later_appearance_sample_resolves_a_contested_handoff():
    first_blue = [1.0] + [0.0]*15
    second_blue = [.73, .27] + [0.0]*14
    before = [
        event('one', 4, 100, end=115, colors=second_blue, point=[.2, .5], recent_colors=json.dumps(first_blue)),
        event('two', 4, 102, end=114, colors=second_blue, point=[.5, .8]),
    ]
    target = event('other view', 12, 116, colors=first_blue, point=[.3, .6])
    assert preview(before + [target])[0]['id'] == 'one'
    before[0].pop('recent_colors')
    assert not preview(before + [target])


def test_vehicle_continuation_uses_motion_or_a_return_to_an_existing_view():
    color = [1.0] + [0.0]*15
    prior = event('maneuver', 8, 100, end=144, label='car', point=[.3, .9], colors=color)
    target = event('exit', 6, 183, label='car', point=[.4, .3], colors=color)
    # An old visibility timestamp alone cannot extend an unrelated vehicle group.
    assert not preview([prior, target])
    prior['last_motion'] = 144
    assert preview([prior, target])[0]['events'][-1]['reason'].startswith('Similar vehicle continuing')
    prior['last_motion'] = 103
    assert not preview([prior, target])
    prior.pop('last_motion')
    earlier = event('entry', 6, 97, label='car', point=[.8, .9], colors=color)
    assert [row['id'] for row in preview([earlier, prior, target])[0]['events']] == ['entry', 'maneuver', 'exit']
    target['plate'], prior['plate'] = 'XY-11-ZZ', 'AB-11-CD'
    assert all(row['id'] != 'exit' for row in preview([earlier, prior, target])[0]['events'])
