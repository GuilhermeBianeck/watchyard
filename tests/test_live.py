from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time

from fastapi.testclient import TestClient

from watchyard.app import create_app
from watchyard.config import Settings
from watchyard.live import Live, LiveFeed
from watchyard.rules import Tracker
from watchyard.service import Service

H={'X-Watchyard-Client':'dashboard'}


class Process:
    def __init__(self):self.code=None;self.terminated=False
    def poll(self):return self.code
    def terminate(self):self.terminated=True;self.code=0
    def kill(self):self.terminate()
    def wait(self,timeout=None):return self.code


def prepared(feed):
    name=feed.generation+'-000001.ts'
    (feed.directory/name).write_bytes(b'video segment')
    (feed.directory/'index.m3u8').write_text('#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1.0,\n'+name+'\n')
    return name


def test_feeds_are_lazy_and_reused_across_simultaneous_viewers(tmp_path,monkeypatch):
    calls=[]
    def spawn(*a,**kw):calls.append(a);return Process()
    monkeypatch.setattr('watchyard.live.subprocess.Popen',spawn)
    live=Live(Settings(tmp_path),threading.Event())
    assert not calls and live.status()['active_cameras']==[]
    feed=live.feeds[1]
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda _:feed.ensure(),range(20)))
    assert len(calls)==1 and live.status()['active_cameras']==[1]
    name=prepared(feed)
    assert name in feed.playlist(wait=0)
    assert feed.playlist(wait=0) and len(calls)==1
    live.close();assert feed.process is None


def test_idle_feed_stops_and_deletes_short_lived_cache(tmp_path,monkeypatch):
    monkeypatch.setattr('watchyard.live.subprocess.Popen',lambda *a,**kw:Process())
    feed=LiveFeed(1,Settings(tmp_path));feed.ensure();proc=feed.process;prepared(feed)
    feed.requested=time.monotonic()-feed.IDLE_SECONDS-1
    feed.reap()
    assert proc.terminated and feed.process is None and not list(feed.directory.iterdir())


def test_live_segments_reject_paths_and_stale_generations(tmp_path,monkeypatch):
    monkeypatch.setattr('watchyard.live.subprocess.Popen',lambda *a,**kw:Process())
    feed=LiveFeed(1,Settings(tmp_path));feed.ensure();name=prepared(feed)
    assert feed.segment(name).read_bytes()==b'video segment'
    for bad in ['../secrets.json','index.m3u8.tmp','a'*12+'-000001.ts','http://private/stream']:
        assert feed.segment(bad) is None
    (feed.directory/'index.m3u8').write_text('#EXTM3U\n#EXT-X-KEY:URI="http://private/secret"\n'+name+'\n')
    assert feed.playlist(wait=0) is None
    feed.close()


def test_dead_encoder_restarts_with_new_urls_and_hardware_fallback(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr('watchyard.live.subprocess.Popen',lambda *a,**kw:calls.append(Process()) or calls[-1])
    feed=LiveFeed(1,Settings(tmp_path));feed.software=False;feed.ensure();old=feed.generation
    calls[0].code=1;feed.retry_after=0;feed.ensure()
    assert feed.software and feed.generation!=old and len(calls)==2
    feed.close()


def test_command_keeps_live_rate_separate_from_analysis(tmp_path):
    settings=Settings(tmp_path);settings.save({'inference_fps':1})
    settings.save_secrets({'NVR_PASSWORD':'p@ss/word','NVR_HOST':'192.168.1.43'})
    feed=LiveFeed(1,settings);feed.generation='a'*12
    args=feed.command()
    assert args[args.index('-r')+1]=='10'
    assert 'p%40ss%2Fword' in args[args.index('-i')+1]
    assert '-an' in args and '-hls_list_size' in args
    assert settings.snapshot()['inference_fps']==1


def test_live_requires_auth_and_viewers_cannot_change_analysis_rate(tmp_path,monkeypatch):
    import ipaddress
    monkeypatch.setattr('watchyard.app.lan_address',lambda:'192.168.1.144')
    monkeypatch.setattr('watchyard.app.lan_network',lambda a:ipaddress.ip_network('192.168.1.0/24'))
    service=Service(Settings(tmp_path));feed=service.live.feeds[1]
    feed.generation='a'*12;name=prepared(feed)
    calls=[];feed.playlist=lambda:calls.append('read') or '#EXTM3U\n'+name+'\n'
    app=create_app(service,run_service=False);owner=TestClient(app)
    viewer=TestClient(app,base_url='http://192.168.1.144:8765',client=('192.168.1.27',50000))
    route='/api/cameras/1/live/'
    assert viewer.get(route+'index.m3u8').status_code==401
    assert viewer.get(route+name).status_code==401 and not calls
    invite=owner.post('/api/invitations',headers=H,json={'kind':'browser','name':'Viewer'}).json()
    viewer.post('/api/login',headers=H,json={'code':invite['code']})
    r=viewer.get(route+'index.m3u8')
    assert r.status_code==200 and r.headers['content-type'].startswith('application/vnd.apple.mpegurl')
    assert r.headers['cache-control']=='no-store'
    assert viewer.get(route+name).content==b'video segment'
    assert viewer.get(route+'index.m3u8.tmp').status_code==404
    assert viewer.post('/api/controls',headers=H,json={'inference_fps':2}).status_code==403
    identity=viewer.get('/api/session').json()['device']['id']
    owner.post('/api/devices/'+identity+'/revoke',headers=H,json={})
    assert viewer.get(route+name).status_code==401
    assert viewer.get(route+'index.m3u8').status_code==401


def test_live_startup_response_is_retryable(tmp_path):
    service=Service(Settings(tmp_path));service.live.feeds[1].playlist=lambda:None
    client=TestClient(create_app(service,run_service=False))
    r=client.get('/api/cameras/1/live/index.m3u8')
    assert r.status_code==503 and r.headers['retry-after']=='1'
    assert client.get('/api/cameras/5/live/index.m3u8').status_code==404


def test_analysis_rate_is_persisted_validated_and_keeps_three_observations(tmp_path):
    service=Service(Settings(tmp_path));client=TestClient(create_app(service,run_service=False))
    assert service.settings.snapshot()['inference_fps']==1
    assert client.post('/api/controls',headers=H,json={'inference_fps':2}).status_code==200
    assert Settings(tmp_path).snapshot()['inference_fps']==2
    for bad in [0,3,10]:assert client.post('/api/controls',headers=H,json={'inference_fps':bad}).status_code==422
    tracker=Tracker();d={'label':'person','confidence':.9,'box':[.2,.2,.3,.7]}
    assert not tracker.update([d],0,[],window=3.5)
    assert not tracker.update([d],1.2,[],window=3.5)
    assert len(tracker.update([d],2.4,[],window=3.5))==1
    assert not tracker.update([d],3.6,[],window=3.5)
