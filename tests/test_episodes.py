import json
import time

from fastapi.testclient import TestClient

from watchyard.app import create_app
from watchyard.config import Settings
from watchyard.service import Service


def setup(tmp_path):
    settings = Settings(tmp_path)
    settings.save_secrets({'TELEGRAM_CHAT_ID': 123})
    service = Service(settings)
    (tmp_path / 'events' / 'snapshot.jpg').write_bytes(b'image')
    calls = []
    service.telegram.photo = lambda *args, **kwargs: calls.append(kwargs)
    return service, calls


def add(service, when, label, *, point=(.45, .67), plate=None, camera=1):
    record = service.camera_config(camera)
    hint = json.dumps({'point': point, 'colors': [1.0] + [0.0]*15})
    key = service.store.add(record, label, .9, 'snapshot.jpg', first_seen=when-3,
                            last_seen=when+4, correlation_hint=hint,
                            last_motion=when if label == 'car' else None)
    with service.store.db:
        service.store.db.execute('UPDATE events SET created=?,plate=? WHERE id=?', (when, plate, key))
    return key


def test_people_and_vehicle_share_one_alert_and_keep_their_tracks_and_replays(tmp_path):
    service, calls = setup(tmp_path)
    now = time.time() - 20
    person = add(service, now, 'person')
    second = add(service, now+2, 'person', point=(.53, .67))
    car = add(service, now+8, 'car', point=(.49, .67))
    service.notifications.deliver_once(service.store)
    assert [call['event_id'] for call in calls] == [person]
    assert len({service.store.event(key)['activity_group'] for key in (person, second, car)}) == 3
    assert {service.store.event(key)['episode_id'] for key in (person, second, car)} == {person}
    for key in (second, car):
        assert service.store.event(key)['status'] == 'grouped'
    client = TestClient(create_app(service, run_service=False))
    group = client.get('/api/activity/preview', params={'group': person}).json()[0]
    assert group['label'] == 'mixed'
    assert [row['id'] for row in group['events']] == [person, second, car]


def test_distant_people_and_a_second_vehicle_keep_their_own_alerts(tmp_path):
    service, calls = setup(tmp_path)
    now = time.time() - 20
    first = add(service, now, 'person', point=(.2, .3))
    other = add(service, now+2, 'person', point=(.8, .8))
    add(service, now+4, 'car', point=(.2, .3), plate='AB-12-CD')
    second_car = add(service, now+6, 'car', point=(.2, .3), plate='XY-12-ZZ')
    service.notifications.deliver_once(service.store)
    assert [call['event_id'] for call in calls] == [first, other, second_car]


def test_episode_allows_one_upgrade_from_silent_to_audible(tmp_path):
    service, calls = setup(tmp_path)
    settings = service.settings
    cameras = settings.snapshot()['cameras']
    cameras[0]['alert_modes']['person'] = 'silent'
    settings.save({'cameras': cameras})
    now = time.time() - 20
    person = add(service, now, 'person')
    car = add(service, now+4, 'car')
    add(service, now+6, 'person')
    service.notifications.deliver_once(service.store)
    assert [(call['event_id'], call['silent']) for call in calls] == [(person, True), (car, False)]
