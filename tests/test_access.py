import time
from fastapi.testclient import TestClient
import watchyard.app as app_module
from watchyard.config import Settings
from watchyard.service import Service
from watchyard.access import Access


def mobile(tmp_path,monkeypatch):
    # The subnet is deliberately deterministic, including on CI.
    import ipaddress
    monkeypatch.setattr(app_module,'lan_address',lambda:'192.168.1.144')
    monkeypatch.setattr(app_module,'lan_network',lambda ip:ipaddress.ip_network('192.168.1.0/24'))
    settings=Settings(tmp_path)
    access=Access(settings)
    settings.save_secrets({'DASHBOARD_CODE_HASH':access.digest('12345678')})
    service=Service(settings)
    app=app_module.create_app(service,run_service=False)
    client=TestClient(app,base_url='http://192.168.1.144:8765',client=('192.168.1.200',51000))
    return client,service,app


def test_lan_camera_data_requires_login(tmp_path,monkeypatch):
    client,_,_=mobile(tmp_path,monkeypatch)
    assert client.get('/').status_code==200
    assert client.get('/api/session').json()['authenticated'] is False
    for path in ['/api/status','/api/events','/api/cameras/1/snapshot','/api/events/'+'a'*32+'.jpg']:
        assert client.get(path).status_code==401


def test_login_cookie_grants_access_and_logout_removes_it(tmp_path,monkeypatch):
    client,_,_=mobile(tmp_path,monkeypatch)
    headers={'X-Watchyard-Client':'dashboard','Origin':'http://192.168.1.144:8765'}
    response=client.post('/api/login',json={'code':'12345678'},headers=headers)
    assert response.status_code==200
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'SameSite=strict' in response.headers['set-cookie']
    assert client.get('/api/status').status_code==200
    assert client.post('/api/controls',json={'enabled':False},headers=headers).status_code==200
    assert client.post('/api/logout',json={},headers=headers).status_code==200
    assert client.get('/api/status').status_code==401


def test_bad_code_is_rate_limited(tmp_path,monkeypatch):
    client,_,_=mobile(tmp_path,monkeypatch)
    headers={'X-Watchyard-Client':'dashboard'}
    for _ in range(5):
        assert client.post('/api/login',json={'code':'00000000'},headers=headers).status_code==401
    assert client.post('/api/login',json={'code':'12345678'},headers=headers).status_code==429


def test_foreign_origin_cannot_pair(tmp_path,monkeypatch):
    client,_,_=mobile(tmp_path,monkeypatch)
    assert client.post('/api/login',json={'code':'12345678'},headers={'X-Watchyard-Client':'dashboard','Origin':'https://evil.invalid'}).status_code==403
    assert client.post('/api/login',json={'code':'12345678'}).status_code==403


def test_forged_expired_and_forwarded_sessions_rejected(tmp_path,monkeypatch):
    client,service,_=mobile(tmp_path,monkeypatch)
    client.cookies.set(Access.cookie,'9999999999.nonce.forged')
    assert client.get('/api/status',headers={'X-Forwarded-For':'127.0.0.1'}).status_code==401
    access=Access(service.settings)
    expired=str(int(time.time()-1))+'.nonce'
    client.cookies.set(Access.cookie,expired+'.'+access.digest(expired))
    assert client.get('/api/status').status_code==401


def test_outside_home_network_is_denied(tmp_path,monkeypatch):
    _,_,app=mobile(tmp_path,monkeypatch)
    with TestClient(app,base_url='http://192.168.1.144:8765',client=('203.0.113.20',50000)) as client:
        assert client.get('/').status_code==403


def test_first_owner_setup_is_local_and_persists_after_sign_out(tmp_path, monkeypatch):
    import ipaddress
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(app_module, 'lan_address', lambda: '192.168.1.144')
    monkeypatch.setattr(app_module, 'lan_network', lambda ip: ipaddress.ip_network('192.168.1.0/24'))
    app = app_module.create_app(Service(Settings(tmp_path)), run_service=False)
    host = 'http://127.0.0.1:8765'
    local = TestClient(app, base_url=host, client=('127.0.0.1', 51000))
    remote = TestClient(app, base_url='http://192.168.1.144:8765', client=('192.168.1.200', 51000))
    credentials = {'username': 'Camera.Owner', 'password': 'test password only', 'name': 'Owner browser'}
    headers = {'X-Watchyard-Client': 'dashboard'}

    state = local.get('/api/session').json()
    assert state['setup_required'] and state['setup_local'] and not state['authenticated']
    assert remote.get('/api/session').json()['setup_required']
    assert not remote.get('/api/session').json()['setup_local']
    assert remote.post('/api/setup', json=credentials, headers=headers | {'X-Forwarded-For': '127.0.0.1'}).status_code == 403
    assert local.post('/api/setup', json=credentials, headers=headers | {'Origin': 'https://evil.invalid'}).status_code == 403
    assert local.post('/api/setup', json=credentials | {'password': 'short'}, headers=headers).status_code == 422

    other = TestClient(app, base_url=host, client=('127.0.0.1', 51001))
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(
            lambda browser: browser.post('/api/setup', json=credentials, headers=headers),
            (local, other),
        ))
    assert sorted(response.status_code for response in responses) == [201, 409]
    owner = local if responses[0].status_code == 201 else other
    assert 'HttpOnly' in next(r for r in responses if r.status_code == 201).headers['set-cookie']
    assert owner.get('/api/session').json()['device']['role'] == 'admin'
    assert len(owner.get('/api/devices').json()['devices']) == 1
    assert owner.post('/api/logout', json={}, headers=headers).status_code == 200
    assert owner.get('/api/status').status_code == 401
    assert owner.get('/healthz/watchdog').status_code == 503
    assert remote.get('/healthz/watchdog').status_code == 403

    restarted = app_module.create_app(Service(Settings(tmp_path)), run_service=False)
    local = TestClient(restarted, base_url=host, client=('127.0.0.1', 51000))
    remote = TestClient(restarted, base_url='http://192.168.1.144:8765', client=('192.168.1.200', 51000))
    state = local.get('/api/session').json()
    assert not state['setup_required'] and state['account_login'] and not state['authenticated']
    assert remote.post('/api/account/login', json=credentials | {'password': 'incorrect password'}, headers=headers).status_code == 401
    assert remote.post('/api/account/login', json=credentials | {'username': 'CAMERA.OWNER'}, headers=headers).status_code == 200
    assert remote.get('/api/session').json()['device']['name'] == 'Owner browser'
    assert remote.get('/api/status').status_code == 200
    account = Access(Settings(tmp_path)).members.owner_account()
    assert len(account['salt']) == 16 and len(account['password_hash']) == 32
    assert credentials['password'].encode() not in account['password_hash']


def test_first_owner_setup_stays_closed_on_existing_install(tmp_path, monkeypatch):
    _, _, app = mobile(tmp_path, monkeypatch)
    local = TestClient(app, base_url='http://127.0.0.1:8765', client=('127.0.0.1', 51000))
    state = local.get('/api/session').json()
    assert state['authenticated'] and state['local'] and not state['setup_required']
    assert local.post(
        '/api/setup',
        headers={'X-Watchyard-Client': 'dashboard'},
        json={'username': 'other', 'password': 'a different password'},
    ).status_code == 409
