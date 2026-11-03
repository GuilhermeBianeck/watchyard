import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from watchyard.app import create_app
from watchyard.config import Settings
from watchyard.overlays import Overlays
from watchyard.replay import ReplayError
from watchyard.service import Service
from watchyard.sources import CameraSources


def car(x):
    return {'label': 'car', 'confidence': .92, 'box': [x, .3, x+.18, .5]}


def test_overlay_survives_misses_and_expires_each_object_independently():
    overlay = Overlays()
    parked, other = car(.15), car(.7)
    overlay.update([parked, other], 10)
    overlay.update([], 11)
    assert overlay.visible(11, ['car']) == [parked, other]
    newer = car(.16)
    overlay.update([newer], 12)
    assert overlay.visible(13, ['car']) == [newer, other]
    assert overlay.visible(14, ['car']) == [newer]
    assert overlay.visible(15, ['person']) == []
    assert overlay.visible(16, ['car']) == []


def test_overlay_endpoint_uses_camera_health_and_analysis_setting(tmp_path):
    service = Service(Settings(tmp_path))
    client = TestClient(create_app(service, run_service=False), client=('127.0.0.1', 12345))
    camera = service.cameras[1]
    camera.captured_at = time.time()
    camera.publish_detections([car(.2)], 1)
    camera.publish_detections([], 2)
    assert client.get('/api/overlays').json()['1'] == [car(.2)]
    camera.captured_at -= 12
    assert client.get('/api/overlays').json()['1'] == []
    camera.captured_at = time.time()
    cameras = service.settings.snapshot()['cameras']
    cameras[0]['enabled'] = False
    service.settings.save({'cameras': cameras})
    assert client.get('/api/overlays').json()['1'] == []


@pytest.mark.parametrize('ids', [[9], [2, 9], [2, 4, 7, 9, 12, 30]])
def test_inventory_drives_capture_live_replay_and_status(tmp_path, ids):
    (tmp_path/'settings.json').write_text(json.dumps({'cameras': [
        {'id': i, 'name': f'View {i}', 'channel': i+1} for i in ids
    ]}))
    secret = 'rtsp://user:private-password@192.0.2.12/stream'
    (tmp_path/'secrets.json').write_text(json.dumps({'CAMERA_RTSP_URLS': {str(ids[-1]): secret}}))
    settings = Settings(tmp_path)
    service = Service(settings)
    assert list(service.cameras) == list(service.live.feeds) == ids
    assert [c['id'] for c in service.status()['cameras']] == ids
    assert f'0/{len(ids)} online' in service.status_text()
    assert secret in service.live.feeds[ids[-1]].command()
    assert 'private-password' not in json.dumps(service.status())
    with pytest.raises(ReplayError, match='not configured'):
        service.clips.recorder.track(ids[-1])
    if len(ids) > 1:
        first = ids[0]
        assert CameraSources(settings).stream(first).endswith(f'/{first+1}02')
        assert service.clips.recorder.track(first) == (first+1)*100+1


def test_inventory_rejects_duplicate_ids_and_public_stream_urls(tmp_path):
    path = tmp_path/'settings.json'
    for cameras in ([{'id': 3, 'name': 'A'}]*2,
                    [{'id': 3, 'name': 'A', 'url': 'rtsp://example.com'}]):
        path.write_text(json.dumps({'cameras': cameras}))
        with pytest.raises(ValueError):
            Settings(tmp_path)


def test_opt_in_providers_fan_out_without_resending_successes(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    service = Service(settings)
    secret = 'a'*64
    settings.save_secrets({
        'NOTIFICATION_PROVIDERS': ['pushover', 'webhook'],
        'PUSHOVER': {'app_token': 'fake-token', 'user_key': 'fake-user'},
        'NOTIFICATION_WEBHOOK': {'url': 'https://example.com/receive', 'signing_secret': secret},
    })
    assert len(service.notifications.targets()) == 2
    assert 'fake-token' not in json.dumps(service.status())
    key = service.store.add({'id': 1, 'name': 'Gate'}, 'dog', .91, 'unused.jpg')
    calls = []
    def post(provider, url, **kwargs):
        calls.append(provider)
        if provider == 'Pushover':
            assert kwargs['data']['priority'] == -1
            assert kwargs['files'] == {}
            return type('Response', (), {'json': lambda self: {'status': 1}})()
        assert url == 'https://example.com/receive'
        headers = kwargs['headers']
        body = kwargs['data']
        stamp = headers['X-Watchyard-Timestamp'].encode()
        assert headers['X-Watchyard-Signature'] == 'sha256='+hmac.new(
            secret.encode(), stamp+b'.'+body, hashlib.sha256).hexdigest()
        assert headers['Idempotency-Key'] == 'event:'+key
        data = json.loads(body)
        assert data['event'] == {'camera_id': 1, 'camera_name': 'Gate', 'label': 'dog', 'confidence': .91}
        assert data['silent'] and 'snapshot' not in data
        if calls.count(provider) == 1:
            raise RuntimeError('Receiver offline')
    monkeypatch.setattr('watchyard.notifications.post', post)
    service.notifications.deliver_once(service.store)
    assert service.store.recent()[0]['status'] == 'pending'
    for table in ('events', 'recipient_deliveries'):
        service.store.db.execute(f'UPDATE {table} SET next_try=0')
    service.store.db.commit()
    service.notifications.deliver_once(service.store)
    assert service.store.recent()[0]['status'] == 'sent'
    assert calls == ['Pushover', 'Custom webhook', 'Custom webhook']


def test_provider_configuration_is_opt_in_and_rejects_cleartext_webhooks(tmp_path):
    service = Service(Settings(tmp_path))
    service.settings.save_secrets({'NOTIFICATION_WEBHOOK': {
        'url': 'http://example.com/hook', 'signing_secret': 'x'*64,
    }})
    assert not service.notifications.targets()
    service.settings.save_secrets({'NOTIFICATION_PROVIDERS': ['webhook']})
    assert not service.notifications.targets()
    service.settings.save_secrets({'NOTIFICATION_WEBHOOK': {
        'url': 'http://127.0.0.1:9876/hook', 'signing_secret': 'x'*64,
    }})
    assert len(service.notifications.targets()) == 1
