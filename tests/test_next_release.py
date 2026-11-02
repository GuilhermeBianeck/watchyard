import datetime as dt
import sqlite3
import time
from types import SimpleNamespace
from fastapi.testclient import TestClient
from watchyard.app import create_app
from watchyard.config import Settings
from watchyard.policy import decision,scheduled
from watchyard.service import Service
from watchyard.store import Store
from watchyard.watchdog import flush_health


def stamp(value):
    return dt.datetime.fromisoformat(value).timestamp()


def test_overnight_schedule_uses_starting_weekday():
    camera={'schedule':{'enabled':True,'days':[0],'start':'22:00','end':'07:00','timezone':'Europe/Lisbon'}}
    assert scheduled(camera,stamp('2026-11-02T22:30:00+00:00'))
    assert scheduled(camera,stamp('2026-11-03T06:59:00+00:00'))
    assert not scheduled(camera,stamp('2026-11-03T07:00:00+00:00'))
    assert not scheduled(camera,stamp('2026-11-03T22:30:00+00:00'))
    camera['schedule']['days']=[]
    assert not scheduled(camera,stamp('2026-11-02T22:30:00+00:00'))


def test_daytime_all_day_and_dst_timezone():
    c={'schedule':{'enabled':True,'days':list(range(7)),'start':'09:00','end':'17:00','timezone':'Europe/Lisbon'}}
    assert scheduled(c,stamp('2026-07-06T08:30:00+00:00')) # 09:30 WEST
    assert not scheduled(c,stamp('2026-11-02T08:30:00+00:00'))
    c['schedule']['start']=c['schedule']['end']='00:00'
    assert scheduled(c,stamp('2026-11-02T08:30:00+00:00'))


def test_global_mute_wins_and_modes_preserve_defaults():
    config={'enabled':True,'muted_until':0}
    assert decision(config,{},'dog',time.time())[0]=='silent'
    assert decision(config,{'alert_modes':{'person':'off'}},'person',time.time())[0]=='off'
    config['muted_until']=time.time()+60
    assert decision(config,{},'person',time.time())[0]=='off'


def test_legacy_migration_preserves_events(tmp_path):
    db=sqlite3.connect(tmp_path/'events.db')
    db.execute('CREATE TABLE events (id TEXT PRIMARY KEY,created REAL,camera INTEGER,camera_name TEXT,label TEXT,confidence REAL,snapshot TEXT,status TEXT,attempts INTEGER DEFAULT 0,next_try REAL DEFAULT 0,detail TEXT DEFAULT "")')
    db.execute('INSERT INTO events (id,created,label) VALUES ("old",1,"person")');db.commit();db.close()
    s=Store(tmp_path);assert s.recent()[0]['id']=='old'
    assert s.feedback('old','useful')
    assert Store(tmp_path).recent()[0]['feedback']=='useful'


def test_health_queue_survives_restart_and_coalesces_recovery(tmp_path):
    s=Store(tmp_path)
    s.observe_health('cam','Gate',False,now=100)
    s.observe_health('cam','Gate',False,now=130)
    assert not s.pending_health()
    s.observe_health('cam','Gate',False,now=146)
    assert len(Store(tmp_path).pending_health())==1
    s.observe_health('cam','Gate',False,now=200)
    assert len(s.pending_health())==1
    s.observe_health('cam','Gate',True,now=210)
    assert len(s.pending_health())==1
    assert 'recovered' in s.pending_health()[0]['body']
    assert any(e['status']=='superseded' for e in s.diagnostics()['health_events'])


def test_transient_outage_does_not_notify(tmp_path):
    s=Store(tmp_path)
    s.observe_health('cam','Gate',True,now=1)
    s.observe_health('cam','Gate',False,now=10)
    s.observe_health('cam','Gate',True,now=20)
    assert not s.pending_health()


def test_health_delivery_failure_keeps_queue(tmp_path):
    s=Store(tmp_path);s.observe_health('cam','Gate',False,now=0);s.observe_health('cam','Gate',False,now=60)
    class Bot:
        def paired(self):return True
        def text(self,*a,**kw):raise RuntimeError('offline')
    flush_health(s,Bot())
    assert s.diagnostics()['health_events'][0]['status']=='pending'
    assert s.diagnostics()['health_events'][0]['attempts']==1


def test_event_delivery_retries_and_reports_latency(tmp_path):
    service=Service(Settings(tmp_path));service.settings.save_secrets({'TELEGRAM_CHAT_ID':1})
    (tmp_path/'events'/'test.jpg').write_bytes(b'image')
    key=service.store.add({'id':1,'name':'Gate'},'person',.9,'test.jpg')
    def fail(*args,**kw):raise RuntimeError('offline')
    service.telegram.photo=fail;service.telegram.deliver_once()
    assert service.telegram.last_delivery_error=='offline'
    # Successful polling must not erase delivery errors.
    service.telegram.last_poll_error=None
    assert service.telegram.last_error=='offline'
    with service.store.lock:
        service.store.db.execute('UPDATE events SET next_try=0 WHERE id=?',(key,));service.store.db.commit()
    photos=[];service.telegram.photo=lambda *a,**kw:photos.append(kw)
    service.telegram.deliver_once()
    assert service.store.recent()[0]['status']=='sent'
    assert service.store.recent()[0]['sent_at'] is not None
    assert service.telegram.last_error is None
    assert photos[0]['silent'] is False
    assert service.store.diagnostics()['delivery_sample_count']==1


def test_alert_policies_and_feedback_api(tmp_path):
    service=Service(Settings(tmp_path));client=TestClient(create_app(service,run_service=False))
    h={'X-Watchyard-Client':'dashboard'}
    policy={'alert_modes':{'person':'normal','car':'off','dog':'silent','cat':'silent'},'schedule':{'enabled':True,'days':[0],'start':'22:00','end':'07:00','timezone':'Europe/Lisbon'}}
    assert client.post('/api/cameras/1/alerts',json=policy,headers=h).status_code==200
    assert Settings(tmp_path).snapshot()['cameras'][0]['alert_modes']['car']=='off'
    policy['schedule']['start']='25:00'
    assert client.post('/api/cameras/1/alerts',json=policy,headers=h).status_code==422
    key=service.store.add({'id':1,'name':'Gate'},'person',.9,'test.jpg','sent')
    assert client.post('/api/events/'+key+'/feedback',json={'value':'false_alarm'},headers=h).status_code==200
    assert client.get('/api/diagnostics').json()['reviews']['false_alarm']==1
    assert client.get('/api/events/export').headers['content-type'].startswith('text/csv')
    assert client.get('/api/events/export').text.startswith('id,created,')
    assert client.post('/api/events/'+key+'/feedback',json={'value':'anything'},headers=h).status_code==422
    assert client.post('/api/events/missing/feedback',json={'value':'useful'},headers=h).status_code==404


def test_local_history_policy_saves_evidence_without_push(tmp_path):
    import numpy as np
    service=Service(Settings(tmp_path));service.settings.save_secrets({'TELEGRAM_CHAT_ID':1})
    config=service.settings.snapshot();camera=config['cameras'][0]
    camera['alert_modes']['person']='off'
    service.record(camera,np.zeros((40,40,3),dtype=np.uint8),{'label':'person','confidence':.8,'box':[.1,.1,.7,.9]},config)
    event=service.store.recent()[0]
    assert event['status']=='recorded'
    assert (tmp_path/'events'/event['snapshot']).is_file()
    assert not service.store.pending()


def test_unauthorized_telegram_review_cannot_change_event(tmp_path):
    service=Service(Settings(tmp_path));service.settings.save_secrets({'TELEGRAM_CHAT_ID':123})
    key=service.store.add({'id':1,'name':'Gate'},'person',.8,'test.jpg')
    service.telegram.text=lambda *a,**k:None
    update={'message':{'text':'/review false_alarm '+key,'chat':{'id':321,'type':'private'},'from':{'id':321}}}
    service.telegram.handle(update)
    assert service.store.recent()[0]['feedback']=='unreviewed'
    update['message']['chat']['id']=update['message']['from']['id']=123
    service.telegram.handle(update)
    assert service.store.recent()[0]['feedback']=='false_alarm'


def test_expired_event_is_never_sent_as_fresh_alert(tmp_path):
    service=Service(Settings(tmp_path));service.settings.save_secrets({'TELEGRAM_CHAT_ID':123})
    key=service.store.add({'id':1,'name':'Gate'},'person',.8,'test.jpg')
    service.store.db.execute('UPDATE events SET created=? WHERE id=?',(time.time()-240,key));service.store.db.commit()
    service.telegram.photo=lambda *a,**k:(_ for _ in ()).throw(AssertionError('stale event sent'))
    service.telegram.deliver_once()
    assert service.store.recent()[0]['status']=='expired'
    assert service.store.recent()[0]['attempts']==0


def test_watchdog_detects_stalled_inference_and_model_failure():
    from watchyard.watchdog import check_service
    import requests
    payload={'detector':'Core ML','detector_error':None,'cameras':[{'enabled':True,'online':True,'detected_at':time.time()}]}
    class Reply:
        def raise_for_status(self):pass
        def json(self):return payload
    class Session:
        def get(self,*a,**kw):return Reply()
    assert check_service(Session())
    payload['cameras'][0]['detected_at']=time.time()-60
    assert not check_service(Session())
    payload['cameras'][0]['detected_at']=time.time()
    payload['detector']='unavailable'
    assert not check_service(Session())
    class Offline:
        def get(self,*a,**kw):raise requests.ConnectionError()
    assert not check_service(Offline())
