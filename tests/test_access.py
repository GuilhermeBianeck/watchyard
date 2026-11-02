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
