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
