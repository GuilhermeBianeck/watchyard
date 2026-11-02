import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from watchyard.runtime import Runtime,data_directory
from watchyard.config import Settings
from watchyard.service import Service
from watchyard.app import create_app
from watchyard.watchdog import check_service


@pytest.fixture(autouse=True)
def clean_runtime(monkeypatch):
    for name in list(os.environ):
        if name.startswith('WATCHYARD_'):
            monkeypatch.delenv(name)


def vps(monkeypatch):
    monkeypatch.setenv('WATCHYARD_DEPLOYMENT','vps')
    monkeypatch.setenv('WATCHYARD_ALLOWED_HOSTS','100.101.102.103,127.0.0.1,localhost,testserver')
    monkeypatch.setenv('WATCHYARD_ALLOWED_CIDRS','100.64.0.0/10')


def test_native_defaults_stay_on_coreml():
    r=Runtime.read(system='Darwin',machine='arm64')
    assert r.backend=='coreml' and r.decoder=='videotoolbox' and r.local_bypass
    assert r.model_path(Path('/data'))==Path('/data/models/yolo11n.mlpackage')
    assert r.prediction_options()=={}


def test_linux_uses_cpu_and_software_decode():
    r=Runtime.read(system='Linux',machine='x86_64')
    assert r.backend=='pytorch' and r.decoder=='software'
    assert r.prediction_options()=={'device':'cpu'}
    assert r.model_path(Path('/data'))==Path('/data/models/yolo11n.pt')


def test_model_override_and_legacy_gateway(monkeypatch):
    monkeypatch.setenv('WATCHYARD_MODEL_PATH','custom.pt')
    monkeypatch.setenv('WATCHYARD_GATEWAY','1')
    r=Runtime.read(system='Linux',machine='x86_64')
    assert r.model_path(Path('/data'))==Path('/data/models/custom.pt')
    assert (r.host,r.port,r.proxy_headers)==('127.0.0.1',8766,True)


def test_portable_data_directories(monkeypatch,tmp_path):
    assert str(data_directory(system='Darwin')).endswith('Library/Application Support/Watchyard')
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path))
    assert data_directory(system='Linux')==tmp_path/'watchyard'
    monkeypatch.setenv('WATCHYARD_DATA',str(tmp_path/'override'))
    assert data_directory(system='Linux')==tmp_path/'override'


def test_vps_fails_closed_without_network_configuration(monkeypatch):
    monkeypatch.setenv('WATCHYARD_DEPLOYMENT','vps')
    with pytest.raises(ValueError,match='ALLOWED_HOSTS'):
        Runtime.read(system='Linux',machine='x86_64')
    vps(monkeypatch)
    monkeypatch.setenv('WATCHYARD_ALLOWED_CIDRS','0.0.0.0/0')
    with pytest.raises(ValueError,match='restricted'):
        Runtime.read(system='Linux',machine='x86_64')


def test_vps_rejects_bypass_and_wildcard_proxy_trust(monkeypatch):
    vps(monkeypatch);monkeypatch.setenv('WATCHYARD_LOCAL_BYPASS','1')
    with pytest.raises(ValueError,match='bypass'):
        Runtime.read(system='Linux',machine='x86_64')
    monkeypatch.setenv('WATCHYARD_LOCAL_BYPASS','0')
    monkeypatch.setenv('WATCHYARD_PROXY_HEADERS','1')
    monkeypatch.setenv('WATCHYARD_TRUSTED_PROXIES','*')
    with pytest.raises(ValueError,match='trusted proxy'):
        Runtime.read(system='Linux',machine='x86_64')


def test_coreml_cannot_be_selected_on_linux(monkeypatch):
    monkeypatch.setenv('WATCHYARD_MODEL_BACKEND','coreml')
    with pytest.raises(ValueError,match='Apple Silicon'):
        Runtime.read(system='Linux',machine='x86_64')


def test_vps_loopback_still_requires_login(monkeypatch,tmp_path):
    vps(monkeypatch)
    service=Service(Settings(tmp_path))
    client=TestClient(create_app(service,run_service=False),client=('127.0.0.1',50000))
    assert not client.get('/api/session').json()['authenticated']
    assert client.get('/api/status').status_code==401
    # Health checks disclose readiness only, without camera data.
    assert client.get('/healthz').status_code==503


def test_private_vpn_requires_auth_and_rejects_other_networks(monkeypatch,tmp_path):
    vps(monkeypatch)
    app=create_app(Service(Settings(tmp_path)),run_service=False)
    vpn=TestClient(app,base_url='http://100.101.102.103:8765',client=('100.80.90.100',50000))
    assert vpn.get('/api/status').status_code==401
    public=TestClient(app,base_url='http://100.101.102.103:8765',client=('203.0.113.99',50000))
    assert public.get('/').status_code==403
    assert vpn.get('/',headers={'Host':'evil.invalid'}).status_code==400


def test_private_watchdog_uses_readiness_without_auth_bypass(monkeypatch):
    monkeypatch.setenv('WATCHYARD_WATCHDOG_HEALTH_ONLY','1')
    class Reply:
        text='ready'
        def raise_for_status(self):pass
    class Session:
        def get(self,url,**kwargs):
            assert url.endswith('/healthz')
            return Reply()
    assert check_service(Session())
