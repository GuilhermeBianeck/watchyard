import ipaddress
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from watchyard.app import create_app
from watchyard.config import Settings
from watchyard.incidents import IncidentSimulation, presence, set_presence
from watchyard.rules import Tracker
from watchyard.service import Service
from watchyard.store import Store


HEADERS = {'X-Watchyard-Client': 'dashboard'}
EXPECTED = [[0, 0], [.4, 0], [.4, 1], [0, 1]]
RESTRICTED = [[.5, 0], [1, 0], [1, 1], [.5, 1]]


def observe(simulation, store, tracker, config, camera, tick, x, *, stamp=10000, label='person'):
    box = [x - .05, .3, x + .05, .7]
    events = tracker.update([{'label': label, 'box': box, 'confidence': .9}], tick, camera['zone'])
    for event in events:
        tracker.tracks[event['track_id']].event_id = store.add(camera, label, .9, 'fixture.jpg', 'recorded')
    simulation.observe(camera, tracker.tracks, config, tick, stamp + tick)


@pytest.mark.parametrize('mode, expected', [('away', 'urgent'), ('home', 'ordinary'), ('paused', None)])
def test_simulation_records_only_observed_entry_and_sustained_activity(tmp_path, mode, expected):
    settings = Settings(tmp_path)
    store = Store(tmp_path)
    simulation = IncidentSimulation(store)
    set_presence(settings, mode, 60 if mode == 'away' else None, now=10000)
    config = settings.snapshot()
    camera = {**config['cameras'][0], 'expected_zone': EXPECTED, 'restricted_zone': RESTRICTED}
    tracker = Tracker()

    for tick, x in enumerate([.35, .35, .35, .44, .52] + [.55] * 8):
        observe(simulation, store, tracker, config, camera, tick, x)
        if tick == 2 and expected:
            assert store.incident_assessments()[0]['zone'] == 'expected'
        if tick == 4 and mode == 'away':
            assert store.incident_assessments()[0]['outcome'] == 'observe'

    rows = store.incident_assessments()
    if expected is None:
        assert rows == []
        return
    assert len(rows) == 1 and rows[0]['outcome'] == expected
    if expected == 'urgent':
        assert rows[0]['dwell_seconds'] == 8
        assert rows[0]['observations'] == 9
        for tick, x in enumerate([.49, .41, .35], 13):
            observe(simulation, store, tracker, config, camera, tick, x)
        assert Store(tmp_path).incident_assessments() == rows
        assert store.event(rows[0]['event_id'])['status'] == 'recorded'


def test_missing_entry_and_observation_gaps_do_not_qualify(tmp_path):
    settings = Settings(tmp_path)
    set_presence(settings, 'away', 60, now=10000)
    config = settings.snapshot()
    camera = {**config['cameras'][0], 'restricted_zone': RESTRICTED}
    store = Store(tmp_path)
    simulation = IncidentSimulation(store)
    tracker = Tracker()
    timeline = [(0, .45), (1, .48), (2, .53), (3, .55)] + [(tick, .55) for tick in range(7, 20)]
    for tick, x in timeline:
        observe(simulation, store, tracker, config, camera, tick, x)
    row, = store.incident_assessments()
    assert row['outcome'] == 'observe'
    assert row['reason'] == 'Person in the restricted area. Entry was not observed.'


def test_expired_presence_is_unknown_and_mute_holds_review(tmp_path):
    settings = Settings(tmp_path)
    set_presence(settings, 'away', 60, now=0)
    assert presence(Settings(tmp_path).snapshot(), 3599)['mode'] == 'away'
    assert presence(Settings(tmp_path).snapshot(), 3600)['mode'] == 'unknown'
    config = settings.snapshot()
    config['muted_until'] = 11000
    camera = {**config['cameras'][0], 'restricted_zone': RESTRICTED}
    store = Store(tmp_path)
    simulation = IncidentSimulation(store)

    for tracker, captured in ((Tracker(), 10000), (Tracker(), 12000)):
        for tick, x in enumerate([.45, .48, .53] + [.55] * 8):
            observe(simulation, store, tracker, config, camera, tick, x, stamp=captured)
    urgent, held = store.incident_assessments()
    assert urgent['outcome'] == 'urgent' and urgent['presence'] == 'unknown'
    assert held['outcome'] == 'held' and held['presence'] == 'unknown'


def test_simulation_runs_after_detection_without_requiring_telegram(tmp_path, monkeypatch):
    service = Service(Settings(tmp_path))
    config = service.settings.snapshot()
    config['incident_presence'] = {'mode': 'away', 'changed_at': 10000, 'until': 13600}
    camera = {**config['cameras'][0], 'restricted_zone': RESTRICTED}

    class Box:
        cls = [0]
        conf = [.9]

        def __init__(self, x):
            from types import SimpleNamespace
            self.xyxy = [SimpleNamespace(cpu=lambda: np.array([x - 5, 30, x + 5, 70]))]

    from types import SimpleNamespace
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    for tick, x in enumerate([45, 48, 53] + [55] * 8):
        service.model = SimpleNamespace(predict=lambda *a, **kw: [SimpleNamespace(boxes=[Box(x)], names=['person'])])
        monkeypatch.setattr('watchyard.service.time.monotonic', lambda: tick)
        service.analyse_frame(service.cameras[1], camera, frame, 10000 + tick, tick + 1, config)
    row, = service.store.incident_assessments()
    event = service.store.event(row['event_id'])
    assert row['outcome'] == 'urgent'
    assert event['status'] == 'unpaired'
    assert service.store.recipient_deliveries(event['id']) == []


def test_admin_controls_and_viewers_cannot_read_presence(tmp_path, monkeypatch):
    monkeypatch.setattr('watchyard.app.lan_address', lambda: '192.168.1.144')
    monkeypatch.setattr('watchyard.app.lan_network', lambda _: ipaddress.ip_network('192.168.1.0/24'))
    service = Service(Settings(tmp_path))
    app = create_app(service, run_service=False)
    owner = TestClient(app)
    assert owner.get('/api/incidents/simulation').json()['presence']['mode'] == 'paused'
    assert owner.post('/api/incidents/presence', headers=HEADERS, json={'mode': 'away', 'minutes': 90}).status_code == 422
    assert owner.post('/api/incidents/presence', json={'mode': 'home'}).status_code == 403
    assert owner.post('/api/incidents/presence', headers=HEADERS, json={'mode': 'away', 'minutes': 60}).json()['mode'] == 'away'

    camera = {'enabled': True, 'zone': [], 'labels': ['person']}
    invalid = owner.post('/api/cameras/1', headers=HEADERS, json={**camera, 'restricted_zone': [[0, 0], [.5, .5], [1, 1]]})
    assert invalid.status_code == 422
    assert owner.post('/api/cameras/1', headers=HEADERS, json={**camera, 'restricted_zone': RESTRICTED}).is_success
    assert owner.post('/api/cameras/1', headers=HEADERS, json=camera).is_success
    assert Settings(tmp_path).snapshot()['cameras'][0]['restricted_zone'] == RESTRICTED

    invitation = owner.post('/api/invitations', headers=HEADERS, json={'kind': 'browser', 'name': 'Viewer'}).json()
    viewer = TestClient(app, base_url='http://192.168.1.144:8765', client=('192.168.1.20', 50000))
    assert viewer.post('/api/login', headers=HEADERS, json={'code': invitation['code']}).is_success
    assert viewer.get('/api/incidents/simulation').status_code == 403
    assert viewer.post('/api/incidents/presence', headers=HEADERS, json={'mode': 'paused'}).status_code == 403
    state = viewer.get('/api/status').json()
    assert 'incident_presence' not in state['settings']
    assert 'restricted_zone' not in state['cameras'][0]
    assert 'restricted_zone' not in state['settings']['cameras'][0]


def test_telegram_presence_command_requires_manage_home(tmp_path):
    settings = Settings(tmp_path)
    settings.save_secrets({'TELEGRAM_CHAT_ID': 123})
    service = Service(settings)
    bot = service.telegram
    bot.members.register('telegram', '456', 'Viewer', 'viewer')
    calls = []
    bot.call = lambda method, data, **_: calls.append((method, data))

    def command(user, text):
        bot.handle({'message': {'text': text, 'chat': {'id': user, 'type': 'private'}, 'from': {'id': user}}})

    command(456, '/presence away 4')
    assert presence(settings.snapshot())['mode'] == 'paused'
    assert 'home manager' in calls[-1][1]['text']
    command(123, '/presence away 4')
    assert presence(settings.snapshot())['until'] > time.time() + 14390
    assert 'Away until' in calls[-1][1]['text']
    command(123, '/presence paused')
    assert presence(settings.snapshot())['mode'] == 'paused'
    assert all(method == 'sendMessage' for method, _ in calls)
