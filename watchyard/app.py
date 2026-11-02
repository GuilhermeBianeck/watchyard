from contextlib import asynccontextmanager
from pathlib import Path
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .service import Service

STATIC = Path(__file__).parent/'static'


class Controls(BaseModel):
    enabled: bool | None = None
    mute_minutes: int | None = Field(None,ge=0,le=1440)
    confidence: float | None = Field(None,ge=0.25,le=0.95)


class CameraUpdate(BaseModel):
    enabled: bool
    labels: list[str]
    zone: list[list[float]] = Field(default_factory=list,max_length=20)


def create_app(service=None, run_service=True):
    service = service or Service(Settings())

    @asynccontextmanager
    async def lifespan(app):
        if run_service:
            service.start()
        yield
        if run_service:
            service.close()

    app = FastAPI(title='Watchyard',version='0.1.0',lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.service = service
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','testserver'])

    @app.middleware('http')
    async def secure_local(request: Request, call_next):
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
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.get('/')
    def index():
        return FileResponse(STATIC/'index.html')

    @app.get('/api/status')
    def status():
        return service.status()

    @app.get('/healthz')
    def health():
        status = service.status()
        ready = status['detector'] not in ('loading','unavailable') and not status['detector_error'] and all(c['online'] and time.time()-c['detected_at']<12 for c in status['cameras'] if c['enabled'])
        return Response('ready' if ready else 'starting or degraded',status_code=200 if ready else 503)

    @app.get('/api/events')
    def events():
        return service.store.recent(80)

    @app.get('/api/cameras/{camera_id}/snapshot')
    def snapshot(camera_id: int):
        camera = service.cameras.get(camera_id)
        if camera is None:
            raise HTTPException(404)
        data = camera.jpeg()
        if data is None:
            raise HTTPException(503,'Camera is reconnecting')
        return Response(data,media_type='image/jpeg')

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
        if not service.telegram.paired():
            raise HTTPException(409,'Pair the Telegram bot first')
        try:
            service.telegram.text('Watchyard test notification. Telegram delivery is working. Walk through a camera view to test object detection.')
        except RuntimeError as exc:
            raise HTTPException(503,str(exc)) from None
        return {'ok':True}

    app.mount('/static',StaticFiles(directory=STATIC),name='static')
    return app


def main():
    import logging
    import uvicorn
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    uvicorn.run(create_app(),host='127.0.0.1',port=8765,access_log=False)


if __name__ == '__main__':
    main()
