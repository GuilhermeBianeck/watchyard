from fastapi.testclient import TestClient
from watchyard.app import create_app
from watchyard.config import Settings
from watchyard.service import Service


def setup(tmp_path):
    service=Service(Settings(tmp_path))
    return service,TestClient(create_app(service,run_service=False))


def test_health_reports_degraded_not_false_ready(tmp_path):
    _,client=setup(tmp_path)
    assert client.get('/healthz').status_code==503


def test_no_secrets_in_status(tmp_path):
    service,client=setup(tmp_path)
    service.settings.save_secrets({'NVR_PASSWORD':'never-show-this','TELEGRAM_BOT_TOKEN':'also-secret','PAIRING_CODE':'secret-code'})
    response=client.get('/api/status')
    assert response.status_code==200
    assert all(secret not in response.text for secret in ['never-show-this','also-secret','secret-code'])


def test_cross_site_changes_are_rejected(tmp_path):
    _,client=setup(tmp_path)
    assert client.post('/api/controls',json={'enabled':False}).status_code==403
    assert client.post('/api/controls',json={'enabled':False},headers={'X-Watchyard-Client':'dashboard','Origin':'https://evil.invalid'}).status_code==403
    assert client.post('/api/controls',json={'enabled':False},headers={'X-Watchyard-Client':'dashboard','Origin':'http://testserver'}).status_code==200


def test_dns_rebinding_host_rejected(tmp_path):
    _,client=setup(tmp_path)
    assert client.get('/api/status',headers={'Host':'evil.invalid'}).status_code==400


def test_zone_validation_and_persistence(tmp_path):
    service,client=setup(tmp_path)
    headers={'X-Watchyard-Client':'dashboard'}
    data={'enabled':True,'labels':['person'],'zone':[[0,0],[1,0]]}
    assert client.post('/api/cameras/1',json=data,headers=headers).status_code==422
    data['zone']=[[0,0],[1,0],[1,1]]
    assert client.post('/api/cameras/1',json=data,headers=headers).status_code==200
    assert Settings(tmp_path).snapshot()['cameras'][0]['zone']==data['zone']
    data['zone']=[[0,0],[1,0],[2,1]]
    assert client.post('/api/cameras/1',json=data,headers=headers).status_code==422


def test_snapshots_never_return_stale_frame(tmp_path):
    import numpy as np
    service,client=setup(tmp_path)
    service.cameras[1].frame=np.zeros((540,960,3),dtype=np.uint8)
    service.cameras[1].captured_at=1
    assert client.get('/api/cameras/1/snapshot').status_code==503


def test_event_paths_cannot_read_arbitrary_files(tmp_path):
    _,client=setup(tmp_path)
    assert client.get('/api/events/secrets.json').status_code==404
    assert client.get('/api/events/'+('f'*32)+'.jpg').status_code==404


def test_telegram_pairing_requires_code_and_owner(tmp_path):
    service,_=setup(tmp_path)
    service.settings.save_secrets({'PAIRING_CODE':'pair-code'})
    sent=[]
    service.telegram.text=lambda message:sent.append(message)
    def update(text,chat=123,user=123,kind='private'):
        return {'message':{'text':text,'chat':{'id':chat,'type':kind},'from':{'id':user}}}
    service.telegram.handle(update('/start wrong'))
    service.telegram.handle(update('/start pair-code',kind='group'))
    service.telegram.handle(update('/start pair-code',user=321))
    assert not service.telegram.paired()
    service.telegram.handle(update('/start pair-code'))
    assert service.settings.secret('TELEGRAM_CHAT_ID')==123
    service.telegram.handle(update('/mute 60',chat=321,user=321))
    assert service.settings.snapshot()['muted_until']==0
    service.telegram.handle(update('/mute 60'))
    assert service.settings.snapshot()['muted_until']>0


def test_notification_retry_queue_survives_restart(tmp_path):
    from watchyard.store import Store
    store=Store(tmp_path)
    key=store.add({'id':1,'name':'Gate'},'person',.8,'example.jpg')
    store.mark(key,'pending','network down',retry_in=60)
    assert Store(tmp_path).recent()[0]['status']=='pending'
    assert not store.pending()
    store.mark(key,'sent')
    assert not store.pending()
