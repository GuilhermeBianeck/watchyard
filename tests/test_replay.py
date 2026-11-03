import datetime as dt
import json
import threading
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
import pytest

from watchyard.app import create_app
from watchyard.config import Settings
from watchyard.replay import Clips, Recorder, ReplayError, parse_time, utc_text
from watchyard.service import Service

H={'X-Watchyard-Client':'dashboard'}


def old_event(service, index=1):
    key=service.store.add({'id':2,'name':'Entrada'},'person',.8,f'{index:032x}.jpg')
    service.store.db.execute('UPDATE events SET created=? WHERE id=?',(time.time()-300,key))
    service.store.db.commit()
    return service.store.event(key)


def ready_clip(service, index=1):
    clip=service.clips.request(old_event(service,index))
    service.clips.path(clip['id']).write_bytes(b'video-data'*100)
    service.clips.path(clip['id'],True).write_bytes(b'poster')
    service.clips.db.execute("UPDATE clips SET state='ready',size=1000,duration=46 WHERE id=?",(clip['id'],))
    service.clips.db.commit()
    return service.clips.get(clip['id'])


@pytest.mark.parametrize('offset_seconds',[0,3600,-18000])
def test_recorder_search_uses_utc_and_ignores_wrong_tracks(tmp_path,offset_seconds):
    settings=Settings(tmp_path)
    settings.save_secrets({'NVR_HOST':'192.168.1.43','NVR_USERNAME':'admin','NVR_PASSWORD':'a@:/password'})
    recorder=Recorder(settings);now=time.time();calls=[]
    def request(method,path,body=None):
        calls.append((method,path,body))
        if path.endswith('/time'):
            clock=dt.datetime.fromtimestamp(now,dt.timezone(dt.timedelta(seconds=offset_seconds))).isoformat()
            return ET.fromstring(f'<Time><localTime>{clock}</localTime></Time>')
        return ET.fromstring(f'''<CMSearchResult><responseStatus>true</responseStatus><matchList>
        <searchMatchItem><trackID>201</trackID><startTime>{utc_text(now-100+offset_seconds)}</startTime><endTime>{utc_text(now+offset_seconds)}</endTime><playbackURI>rtsp://evil.invalid/video</playbackURI></searchMatchItem>
        <searchMatchItem><trackID>301</trackID><startTime>{utc_text(now-100+offset_seconds)}</startTime><endTime>{utc_text(now+offset_seconds)}</endTime></searchMatchItem>
        </matchList></CMSearchResult>''')
    recorder.request=request
    spans=recorder.search(2,now-90,now-10)
    assert len(spans)==1 and spans[0]==(now-90,now-10)
    body=ET.fromstring(calls[-1][2])
    assert body.findtext('trackList/trackID')=='201'
    assert body.findtext('timeSpanList/timeSpan/startTime')==utc_text(now-90+offset_seconds)
    uri=recorder.replay_url(2,now-90,now-10)
    assert 'evil.invalid' not in uri and '/Streaming/tracks/201/' in uri
    assert 'a%40%3A%2Fpassword' in uri
    assert 'starttime='+utc_text(now-90+offset_seconds,True) in uri


def test_recorder_clock_skew_stops_wrong_moment_replay(tmp_path):
    recorder=Recorder(Settings(tmp_path))
    recorder.request=lambda *a:ET.fromstring(f'<Time><localTime>{utc_text(time.time()+3600)}</localTime></Time>')
    with pytest.raises(ReplayError,match='clock differs'):
        recorder.search(1,time.time()-500,time.time()-450)
    with pytest.raises(ValueError):parse_time('2026-11-02T12:00:00')


def test_replay_deduplicates_requests_and_waits_for_post_alert_recording(tmp_path):
    service=Service(Settings(tmp_path));event=old_event(service)
    first=service.clips.request(event);second=service.clips.request(event)
    assert first['id']==second['id']
    event['id']='b'*32;event['created']=time.time()
    fresh=service.clips.request(event)
    assert service.clips.public(fresh)['waiting_for_recording']
    assert fresh['start']==event['created']-10 and fresh['end']==event['created']+30


def test_replay_queue_and_disk_limits(tmp_path,monkeypatch):
    clips=Clips(Settings(tmp_path),threading.Event())
    event={'id':'a'*32,'camera':1,'camera_name':'Gate','label':'person','created':time.time()-100}
    monkeypatch.setattr('watchyard.replay.shutil.disk_usage',lambda p:SimpleNamespace(free=100))
    with pytest.raises(ReplayError,match='free space'):clips.request(event)
    monkeypatch.setattr('watchyard.replay.shutil.disk_usage',lambda p:SimpleNamespace(free=10*1024**3))
    for i in range(8):clips.request(event|{'id':f'{i:032x}'})
    with pytest.raises(ReplayError,match='queue is full'):clips.request(event)


def test_unavailable_recordings_do_not_start_conversion(tmp_path):
    service=Service(Settings(tmp_path));clip=service.clips.request(old_event(service))
    service.clips.recorder.search=lambda *a:[]
    service.clips.run_process=lambda *a:pytest.fail('No video process should run without a recording')
    assert service.clips.work_once()
    result=service.clips.get(clip['id'])
    assert result['state']=='unavailable' and 'No recording' in result['error']


def test_errors_never_expose_credentials_and_can_be_retried(tmp_path):
    service=Service(Settings(tmp_path));event=old_event(service);clip=service.clips.request(event)
    def fail(*a):raise RuntimeError('rtsp://admin:secret@private-device')
    service.clips.recorder.search=fail
    service.clips.work_once();result=service.clips.get(clip['id'])
    assert result['state']=='failed' and 'secret' not in json.dumps(service.clips.public(result))
    assert service.clips.request(event)['state']=='queued'


def test_pending_replay_survives_restart_and_shutdown(tmp_path):
    service=Service(Settings(tmp_path));clip=service.clips.request(old_event(service))
    service.clips.db.execute("UPDATE clips SET state='preparing'");service.clips.db.commit()
    reloaded=Clips(service.settings,threading.Event())
    assert reloaded.get(clip['id'])['state']=='queued'
    def shutdown(*a):
        reloaded.stop.set();raise ReplayError('stopped')
    reloaded.prepare=shutdown;reloaded.work_once()
    assert reloaded.get(clip['id'])['state']=='queued'


def test_saved_clips_survive_event_retention_and_cache_eviction(tmp_path):
    service=Service(Settings(tmp_path));kept=ready_clip(service);cached=ready_clip(service,2)
    service.clips.keep(kept['id'],True)
    service.clips.db.execute('UPDATE clips SET accessed=0');service.clips.db.commit()
    service.store.db.execute('UPDATE events SET created=0');service.store.db.commit()
    service.store.cleanup(7);service.clips.cleanup()
    assert not service.store.recent()
    assert service.clips.path(kept['id']).exists()
    assert service.clips.saved()[0]['event_id']==kept['event_id']
    assert not service.clips.path(cached['id']).exists()
    assert service.clips.get(cached['id']) is None or service.clips.get(cached['id'])['state']=='expired'
    unkept=service.clips.keep(kept['id'],False)
    service.clips.cleanup()
    assert not unkept['saved'] and service.clips.path(kept['id']).exists()


def test_missing_cached_file_is_prepared_again(tmp_path):
    service=Service(Settings(tmp_path));clip=ready_clip(service)
    service.clips.path(clip['id']).unlink()
    assert service.clips.request(service.store.event(clip['event_id']))['state']=='queued'


def test_keep_budget_does_not_remove_other_saved_clips(tmp_path):
    service=Service(Settings(tmp_path));first=ready_clip(service);second=ready_clip(service,2)
    service.clips.SAVED_BYTES=1500
    service.clips.keep(first['id'],True)
    with pytest.raises(ReplayError,match='reached 2 GB'):service.clips.keep(second['id'],True)
    assert service.clips.get(first['id'])['saved'] and not service.clips.get(second['id'])['saved']


def test_viewer_can_prepare_and_download_but_not_keep_and_revocation_stops_ranges(tmp_path,monkeypatch):
    import ipaddress
    monkeypatch.setattr('watchyard.app.lan_address',lambda:'192.168.1.144')
    monkeypatch.setattr('watchyard.app.lan_network',lambda a:ipaddress.ip_network('192.168.1.0/24'))
    service=Service(Settings(tmp_path));clip=ready_clip(service)
    app=create_app(service,run_service=False);owner=TestClient(app)
    viewer=TestClient(app,base_url='http://192.168.1.144:8765',client=('192.168.1.27',50000))
    route='/api/clips/'+clip['id']
    assert viewer.get(route+'/video',headers={'Range':'bytes=0-9'}).status_code==401
    invite=owner.post('/api/invitations',headers=H,json={'kind':'browser','name':'Viewer'}).json()
    assert viewer.post('/api/login',headers=H,json={'code':invite['code']}).status_code==200
    assert viewer.post('/api/events/'+clip['event_id']+'/replay',headers=H,json={}).json()['id']==clip['id']
    response=viewer.get(route+'/video',headers={'Range':'bytes=10-19'})
    assert response.status_code==206 and response.content==b'video-data'
    assert response.headers['content-range']=='bytes 10-19/1000'
    assert response.headers['cache-control']=='no-store'
    head=viewer.head(route+'/video')
    assert head.status_code==200 and head.headers['content-length']=='1000' and head.content==b''
    assert 'attachment' in viewer.get(route+'/video?download=true').headers['content-disposition']
    assert viewer.get(route+'/poster').status_code==200
    assert viewer.post(route+'/keep',headers=H,json={'saved':True}).status_code==403
    assert owner.post(route+'/keep',headers=H,json={'saved':True}).status_code==200
    assert len(viewer.get('/api/clips/saved').json())==1
    identity=viewer.get('/api/session').json()['device']['id']
    owner.post('/api/devices/'+identity+'/revoke',headers=H,json={})
    assert viewer.get(route+'/video',headers={'Range':'bytes=20-29'}).status_code==401
    assert viewer.head(route+'/video').status_code==401


def test_replay_post_keeps_origin_and_request_checks(tmp_path):
    service=Service(Settings(tmp_path));event=old_event(service)
    client=TestClient(create_app(service,run_service=False));route='/api/events/'+event['id']+'/replay'
    assert client.post(route,json={}).status_code==403
    assert client.post(route,json={},headers=H|{'Origin':'https://evil.invalid'}).status_code==403
    assert client.get('/api/clips/'+'a'*32+'/video').status_code==404
    assert client.get('/api/clips/../secrets.json/video').status_code==404


def test_telegram_alert_has_private_authenticated_replay_link(tmp_path,monkeypatch):
    monkeypatch.setenv('WATCHYARD_GATEWAY','1')
    monkeypatch.setattr('watchyard.access.lan_address',lambda:'192.168.1.144')
    service=Service(Settings(tmp_path));service.settings.save_secrets({'TELEGRAM_CHAT_ID':123})
    service.telegram.members.sync_owner()
    calls=[];service.telegram.call=lambda method,data=None,**kw:calls.append(data)
    service.telegram.photo(b'picture','Alert',event_id='a'*32)
    keyboard=json.loads(calls[0]['reply_markup'])['inline_keyboard']
    links=[b['url'] for row in keyboard for b in row if 'url' in b]
    assert links==['http://192.168.1.144:8765/#event='+'a'*32]
    assert 'watchyard_session' not in links[0] and '@' not in links[0]
