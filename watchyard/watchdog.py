"""Independent same-host watchdog. Cannot detect a powered-off host."""
import json
import os
import time
import requests
from .config import Settings
from .store import Store
from .telegram import Telegram
from .notifications import Notifications


def check_service(session):
    try:
        health_only=os.environ.get('WATCHYARD_WATCHDOG_HEALTH_ONLY')=='1'
        url='http://127.0.0.1:8765/'+('healthz' if health_only else 'api/status')
        response=session.get(url,timeout=5)
        if not health_only and getattr(response,'status_code',None) == 401:
            response = session.get('http://127.0.0.1:8765/healthz/watchdog',timeout=5)
            health_only = True
        response.raise_for_status()
        if health_only:
            return response.text.strip()=='ready'
        status=response.json()
        if status['detector'] in ('loading', 'unavailable') or status['detector_error']:
            return False
        online = [camera for camera in status['cameras'] if camera['enabled'] and camera['online']]
        # The service reports individual camera failures separately.
        return not online or any(
            not camera.get('analysis_error') and time.time() - camera['detected_at'] < 45
            for camera in online
        )
    except (requests.RequestException,ValueError,KeyError):
        return False


def main():
    settings=Settings()
    store=Store(settings.path)
    bot=Telegram(settings,None)
    notifications=Notifications(settings,bot)
    session=requests.Session();session.trust_env=False
    started=time.time()
    while True:
        healthy=check_service(session)
        if time.time()-started>90:
            store.observe_health('service','Watchyard detector or dashboard',healthy)
        notifications.flush_health(store)
        tmp=settings.path/'watchdog-state.tmp'
        tmp.write_text(json.dumps({'checked_at':time.time(),'healthy':healthy,'scope':'same host'}))
        tmp.replace(settings.path/'watchdog-state.json')
        time.sleep(15)


if __name__=='__main__':
    main()
