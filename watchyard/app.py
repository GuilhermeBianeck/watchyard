from contextlib import asynccontextmanager
from pathlib import Path
import ipaddress
import socket
import subprocess
import time
import csv
import io
import json
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import Settings
from .service import Service
from .access import Access, lan_address, lan_network
from .runtime import Runtime
from .replay import ReplayError

STATIC = Path(__file__).parent/'static'


class Controls(BaseModel):
    enabled: bool | None = None
    mute_minutes: int | None = Field(None,ge=0,le=1440)
    confidence: float | None = Field(None,ge=0.25,le=0.95)
    inference_fps: Literal[1,2] | None = None


class Login(BaseModel):
    code: str = Field(min_length=1,max_length=64)
    name: str = Field('New browser',min_length=1,max_length=60)


class CameraUpdate(BaseModel):
    enabled: bool
    labels: list[str]
    zone: list[list[float]] = Field(default_factory=list,max_length=20)


class Schedule(BaseModel):
    enabled: bool = False
    days: list[int] = Field(default_factory=lambda:list(range(7)),max_length=7)
    start: str = Field('22:00',pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    end: str = Field('07:00',pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    timezone: str = 'Europe/Lisbon'

    @field_validator('days')
    @classmethod
    def days_valid(cls,value):
        if len(set(value))!=len(value) or any(d<0 or d>6 for d in value):
            raise ValueError('Choose distinct weekdays from Monday to Sunday')
        return value

    @field_validator('timezone')
    @classmethod
    def timezone_valid(cls,value):
        try: ZoneInfo(value)
        except (ZoneInfoNotFoundError,ValueError): raise ValueError('Unknown timezone')
        return value


class AlertPolicy(BaseModel):
    alert_modes: dict[str,Literal['normal','silent','off']]
    schedule: Schedule

    @field_validator('alert_modes')
    @classmethod
    def modes_valid(cls,value):
        if set(value)!={'person','car','dog','cat'}:
            raise ValueError('Provide a preference for all four object categories')
        return value


class Feedback(BaseModel):
    value: Literal['useful','false_alarm','unreviewed']


class Invitation(BaseModel):
    kind: Literal['browser','telegram']
    name: str = Field(min_length=1,max_length=60)
    role: Literal['admin','viewer'] = 'viewer'

    @field_validator('name')
    @classmethod
    def name_valid(cls,value):
        value=value.strip()
        if not value:raise ValueError('Give the device or account a name')
        return value


class KeepClip(BaseModel):
    saved: bool


def create_app(service=None, run_service=True):
    service = service or Service(Settings())
    access = Access(service.settings)
    runtime = Runtime.read()
    address = lan_address()
    home = lan_network(address)
    hostname = socket.gethostname().lower()
    try:
        bonjour = subprocess.check_output(['/usr/sbin/scutil','--get','LocalHostName'],text=True,timeout=2).strip().lower()+'.local'
    except (OSError,subprocess.SubprocessError):
        bonjour = hostname.split('.')[0]+'.local'

    @asynccontextmanager
    async def lifespan(app):
        if run_service:
            service.start()
        yield
        if run_service:
            service.close()

    app = FastAPI(title='Watchyard',version=__version__,lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.service = service
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=list(runtime.allowed_hosts) if runtime.allowed_hosts else ['localhost','127.0.0.1','testserver',address,hostname,hostname.split('.')[0]+'.local',bonjour])

    @app.middleware('http')
    async def secure_local(request: Request, call_next):
        client = request.client.host
        if not access.local(client):
            try:
                ip = ipaddress.ip_address(client)
                if not any(ip in network for network in (runtime.allowed_networks or (home,))):
                    return Response('Home network access only',status_code=403)
            except ValueError:
                return Response('Home network access only',status_code=403)
        principal=access.principal(request)
        request.state.principal = principal
        if request.url.path.startswith('/api/') and request.url.path not in ('/api/session','/api/login'):
            if not principal:
                return JSONResponse({'detail':'Sign in with your dashboard code'},status_code=401)
            replay_request=request.method=='POST' and re.fullmatch(r'/api/events/[0-9a-f]{32}/replay',request.url.path)
            administrative=request.url.path.startswith(('/api/devices','/api/invitations')) or (request.method not in ('GET','HEAD','OPTIONS') and request.url.path!='/api/logout' and not replay_request)
            if administrative and principal['role']!='admin':
                return JSONResponse({'detail':'This device has view-only access'},status_code=403)
        if request.method not in ('GET','HEAD','OPTIONS'):
            if request.headers.get('x-watchyard-client') != 'dashboard':
                return Response('Dashboard request required',status_code=403)
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return Response('Origin rejected',status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.get('/')
    def index():
        return FileResponse(STATIC/'index.html')

    @app.get('/api/session')
    def session(request: Request):
        return {'authenticated':access.authenticated(request),'local':runtime.local_bypass and access.local(request.client.host),'device':access.principal(request)}

    @app.post('/api/login')
    def login(data: Login, request: Request):
        token, status = access.login(data.code.strip().replace(' ',''),request.client.host,data.name.strip() or 'New browser')
        if not token:
            raise HTTPException(status,'Try again in five minutes' if status==429 else 'Incorrect dashboard code')
        response = JSONResponse({'ok':True})
        response.set_cookie(access.cookie,token,max_age=30*86400,httponly=True,samesite='strict',secure=request.url.scheme=='https')
        return response

    @app.post('/api/logout')
    def logout(request:Request):
        token=request.cookies.get(access.cookie,'')
        if token:access.members.revoke_session(access.digest(token))
        response = JSONResponse({'ok':True})
        response.delete_cookie(access.cookie)
        return response

    def dashboard_address(request):
        candidates=[h for h in runtime.allowed_hosts if h not in ('127.0.0.1','localhost','testserver')]
        target=candidates[0] if candidates else address
        port=request.url.port
        return request.url.scheme+'://'+target+(':'+str(port) if port else '')

    @app.get('/api/devices')
    def devices(request:Request):
        return {'devices':access.members.devices(),'invitations':access.members.invitations(),'current':access.principal(request),'dashboard_url':dashboard_address(request)}

    @app.post('/api/invitations')
    def invite(data:Invitation,request:Request):
        if data.kind == 'telegram' and not service.telegram.username:
            raise HTTPException(409,'Connect the Telegram bot before creating Telegram invitations')
        try:
            result=access.members.invite(data.kind,data.name.strip(),data.role)
        except ValueError as exc:
            raise HTTPException(409,str(exc)) from None
        if data.kind=='telegram':
            result['url']='https://t.me/'+service.telegram.username+'?start='+result['code']
        else:
            result['url']=dashboard_address(request)+'/#join='+result['code']
        return result

    @app.post('/api/invitations/{invite_id}/revoke')
    def revoke_invitation(invite_id:str):
        if not access.members.cancel(invite_id):raise HTTPException(404)
        return {'ok':True}

    @app.post('/api/devices/{device_id}/revoke')
    def revoke_device(device_id:str):
        if not access.members.revoke(device_id):raise HTTPException(404)
        return {'ok':True}

    @app.get('/api/overlays')
    def overlays():
        return service.overlays()

    @app.get('/api/status')
    def status():
        return service.status()

    @app.get('/healthz')
    def health():
        ready = service.ready()
        return Response('ready' if ready else 'starting or degraded',status_code=200 if ready else 503)

    def public_event(event, owner):
        event.pop('correlation_hint', None)
        if not owner:
            event.pop('plate', None)
        elif event.get('plate'):
            aliases = service.settings.secret('PLATE_ALIASES', {})
            if isinstance(aliases, dict) and isinstance(aliases.get(event['plate']), str):
                event['vehicle_name'] = aliases[event['plate']]
        return event

    @app.get('/api/activity/preview')
    def activity_preview(group: str | None = None):
        from .correlation import preview

        rows = service.store.correlation_events()
        if group and re.fullmatch(r'[0-9a-f]{32}', group):
            items = preview(rows, limit=None, include_single=True)
            selected = [item for item in items if item['id'] == group]
            others = [item for item in items if item['id'] != group and len(item['events']) > 1]
            return (selected + others)[:12]
        return preview(rows)

    @app.get('/api/events')
    def events(request: Request):
        owner = request.state.principal['role'] == 'admin'
        return [public_event(event, owner) for event in service.store.recent(80)]

    @app.get('/api/events/export')
    def export_events():
        stream=io.StringIO()
        fields=['id','created','camera_name','label','confidence','status','feedback','sent_at','attempts','detail']
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        writer.writerows(service.store.recent(5000))
        return Response(stream.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="watchyard-events.csv"'})

    @app.get('/api/events/{event_id}/details')
    def event_details(event_id:str, request: Request):
        event=service.store.event(event_id)
        if event is None:raise HTTPException(404,'This alert is no longer in history. Check Saved clips in Activity.')
        return public_event(event, request.state.principal['role'] == 'admin')

    @app.post('/api/events/{event_id}/replay')
    def request_replay(event_id:str):
        event=service.store.event(event_id)
        if event is None:raise HTTPException(404,'This alert is no longer in history. Kept clips remain in Activity.')
        try:return service.clips.public(service.clips.request(event))
        except ReplayError as exc:raise HTTPException(409,str(exc)) from None

    @app.get('/api/clips/saved')
    def saved_clips():
        return service.clips.saved()

    def find_clip(clip_id):
        clip=service.clips.get(clip_id)
        if clip is None:raise HTTPException(404,'Replay not found')
        return clip

    @app.get('/api/clips/{clip_id}')
    def clip_status(clip_id:str):
        return service.clips.public(find_clip(clip_id))

    @app.post('/api/clips/{clip_id}/keep')
    def keep_clip(clip_id:str,data:KeepClip):
        find_clip(clip_id)
        try:return service.clips.public(service.clips.keep(clip_id,data.saved))
        except ReplayError as exc:raise HTTPException(409,str(exc)) from None

    @app.api_route('/api/clips/{clip_id}/video',methods=['GET','HEAD'])
    def clip_video(clip_id:str,download:bool=False):
        clip=find_clip(clip_id)
        path=service.clips.path(clip_id)
        if clip['state']!='ready' or not path.is_file():raise HTTPException(409,'Prepare the replay before playing it.')
        service.clips.touch(clip_id)
        from .replay import utc_text
        filename=f"Watchyard-camera-{clip['camera']}-{utc_text(clip['event_created'],True)}.mp4"
        return FileResponse(path,media_type='video/mp4',filename=filename,
                            content_disposition_type='attachment' if download else 'inline')

    @app.api_route('/api/clips/{clip_id}/poster',methods=['GET','HEAD'])
    def clip_poster(clip_id:str):
        clip=find_clip(clip_id)
        path=service.clips.path(clip_id,True)
        if clip['state']!='ready' or not path.is_file():raise HTTPException(404)
        return FileResponse(path,media_type='image/jpeg')

    @app.post('/api/events/{event_id}/feedback')
    def feedback(event_id:str,data:Feedback):
        if not service.store.feedback(event_id,data.value):
            raise HTTPException(404,'Event not found')
        return {'ok':True}

    @app.get('/api/diagnostics')
    def diagnostics():
        data=service.store.diagnostics()
        try:
            state=json.loads((service.settings.path/'watchdog-state.json').read_text())
            data['watchdog']={'checked_at':state['checked_at'],'healthy':state['healthy'],'fresh':time.time()-state['checked_at']<60}
        except (OSError,ValueError,KeyError):
            data['watchdog']=None
        return data

    @app.get('/api/cameras/{camera_id}/snapshot')
    def snapshot(camera_id: int):
        camera = service.cameras.get(camera_id)
        if camera is None:
            raise HTTPException(404)
        data = camera.jpeg()
        if data is None:
            raise HTTPException(503,'Camera is reconnecting')
        return Response(data,media_type='image/jpeg')

    @app.get('/api/cameras/{camera_id}/live/index.m3u8')
    def live_playlist(camera_id:int):
        feed=service.live.feeds.get(camera_id)
        if feed is None:raise HTTPException(404)
        text=feed.playlist()
        if text is None:
            return Response('Live video is connecting. Please retry.',status_code=503,headers={'Retry-After':'1'})
        return Response(text,media_type='application/vnd.apple.mpegurl')

    @app.get('/api/cameras/{camera_id}/live/{filename}')
    def live_segment(camera_id:int,filename:str):
        feed=service.live.feeds.get(camera_id)
        path=feed.segment(filename) if feed else None
        if path is None:raise HTTPException(404)
        return FileResponse(path,media_type='video/mp2t')

    @app.get('/api/events/{filename}')
    def event_image(filename: str):
        if len(filename)!=36 or not filename.endswith('.jpg') or any(c not in '0123456789abcdef' for c in filename[:-4]):
            raise HTTPException(404)
        path = service.settings.path/'events'/filename
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    @app.post('/api/controls')
    def controls(data: Controls):
        changes = data.model_dump(exclude_none=True,exclude={'mute_minutes'})
        if data.mute_minutes is not None:
            changes['muted_until'] = time.time()+60*data.mute_minutes if data.mute_minutes else 0
        service.settings.save(changes)
        return {'ok':True}

    @app.post('/api/cameras/{camera_id}')
    def camera_settings(camera_id:int, data:CameraUpdate):
        if not set(data.labels) <= {'person','car','dog','cat'}:
            raise HTTPException(422,'Unknown object category')
        if data.zone and len(data.zone)<3:
            raise HTTPException(422,'A zone needs at least three points')
        if any(len(p)!=2 or any(not 0<=v<=1 for v in p) for p in data.zone):
            raise HTTPException(422,'Invalid zone coordinates')
        cameras = service.settings.snapshot()['cameras']
        c = next((c for c in cameras if c['id']==camera_id),None)
        if c is None:
            raise HTTPException(404)
        c.update(data.model_dump())
        service.settings.save({'cameras':cameras})
        # A rule change starts new tracking; existing parked cars still require movement.
        from .rules import Tracker
        service.trackers[camera_id] = Tracker()
        return {'ok':True}

    @app.post('/api/test-notification')
    def test_notification():
        targets = service.notifications.targets()
        if not targets:
            raise HTTPException(409,'Configure an alert destination first')
        try:
            service.notifications.send_test(targets)
        except RuntimeError as exc:
            raise HTTPException(503,str(exc)) from None
        return {'ok':True}

    @app.post('/api/cameras/{camera_id}/alerts')
    def alert_policy(camera_id:int,data:AlertPolicy):
        cameras=service.settings.snapshot()['cameras']
        camera=next((c for c in cameras if c['id']==camera_id),None)
        if camera is None:
            raise HTTPException(404)
        camera.update(data.model_dump())
        service.settings.save({'cameras':cameras})
        return {'ok':True}

    app.mount('/static',StaticFiles(directory=STATIC),name='static')
    return app


def main():
    import logging
    import os
    import uvicorn
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    runtime = Runtime.read()
    uvicorn.run(create_app(),host=runtime.host,port=runtime.port,access_log=False,proxy_headers=runtime.proxy_headers,forwarded_allow_ips=runtime.trusted_proxies)


if __name__ == '__main__':
    main()
