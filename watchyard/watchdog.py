"""Independent same-host watchdog. Cannot detect a powered-off host."""
import json
import os
import time
import requests
from .config import Settings
from .store import Store
from .telegram import Telegram


def check_service(session):
    try:
        health_only=os.environ.get('WATCHYARD_WATCHDOG_HEALTH_ONLY')=='1'
        url='http://127.0.0.1:8765/'+('healthz' if health_only else 'api/status')
        response=session.get(url,timeout=5)
        response.raise_for_status()
        if health_only:
            return response.text.strip()=='ready'
        status=response.json()
        return (status['detector'] not in ('loading','unavailable') and not status['detector_error'] and all(time.time()-c['detected_at']<45 for c in status['cameras'] if c['enabled'] and c['online']))
    except (requests.RequestException,ValueError,KeyError):
        return False


def flush_health(store,bot):
    if not bot.paired():
        return
    for event in store.pending_health():
        try:
            age=time.time()-event['created']
            message=event['body']
            if age>60:
                message+='\nQueued at '+time.strftime('%d %b %H:%M:%S %Z',time.localtime(event['created']))+'. Delivery was delayed.'
            bot.text(message,disable_notification='true')
            store.mark_health(event['id'],True)
        except RuntimeError:
            store.mark_health(event['id'],False,retry_in=min(300,15*2**min(event['attempts'],4)))


def main():
    settings=Settings()
    store=Store(settings.path)
    bot=Telegram(settings,None)
    session=requests.Session();session.trust_env=False
    started=time.time()
    while True:
        healthy=check_service(session)
        if time.time()-started>90:
            store.observe_health('service','Watchyard detector or dashboard',healthy)
        flush_health(store,bot)
        tmp=settings.path/'watchdog-state.tmp'
        tmp.write_text(json.dumps({'checked_at':time.time(),'healthy':healthy,'scope':'same host'}))
        tmp.replace(settings.path/'watchdog-state.json')
        time.sleep(15)


if __name__=='__main__':
    main()
