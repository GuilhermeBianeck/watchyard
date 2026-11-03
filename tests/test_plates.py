from watchyard.plates import consensus, normalize


def test_plate_consensus_requires_multiple_frames_and_rejects_ambiguity():
    assert normalize('AB 12 CD') == 'AB-12-CD'
    assert normalize('AB-12-C0') is None
    assert consensus([['AB 12 CD', 'AB-12-CD'], []]) is None
    assert consensus([['AB 12 CD'], ['AB-12-CD']]) == 'AB-12-CD'
    assert consensus([['AB 12 CD', 'XY 34 ZZ'], ['AB-12-CD', 'XY-34-ZZ']]) is None


def test_plate_data_is_visible_only_to_managers(tmp_path, monkeypatch):
    import ipaddress

    from fastapi.testclient import TestClient
    from watchyard.app import create_app
    from watchyard.config import Settings
    from watchyard.service import Service

    monkeypatch.setattr('watchyard.app.lan_address', lambda: '192.168.1.144')
    monkeypatch.setattr('watchyard.app.lan_network', lambda _: ipaddress.ip_network('192.168.1.0/24'))
    settings = Settings(tmp_path)
    settings.save_secrets({'PLATE_ALIASES': {'AB-12-CD': 'Family car'}})
    service = Service(settings)
    event_id = service.store.add({'id': 1, 'name': 'Gate'}, 'car', .9, 'test.jpg')
    service.store.save_plate(event_id, 'AB-12-CD')
    app = create_app(service, run_service=False)
    owner = TestClient(app)
    viewer = TestClient(app, base_url='http://192.168.1.144:8765', client=('192.168.1.27', 50000))
    headers = {'X-Watchyard-Client': 'dashboard'}
    invitation = owner.post('/api/invitations', headers=headers,
                            json={'kind': 'browser', 'name': 'Viewer'}).json()
    route = f'/api/events/{event_id}/details'
    assert owner.get(route).json()['vehicle_name'] == 'Family car'
    assert viewer.post('/api/login', headers=headers, json={'code': invitation['code']}).status_code == 200
    assert viewer.get(route).status_code == 200
    assert 'plate' not in viewer.get(route).json()
    assert 'plate' not in viewer.get('/api/events').json()[0]
