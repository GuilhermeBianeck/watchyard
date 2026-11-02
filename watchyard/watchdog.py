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
        key='health:'+event['id']
        targets={r['id']:r for r in bot.recipient_devices()}
        store.ensure_recipients(key,list(targets.values()))
        for delivery in store.recipient_deliveries(key):
            if delivery['status']!='pending':continue
            target=targets.get(delivery['recipient'])
            if not target:
                store.recipient_result(key,delivery['recipient'],'cancelled');continue
            if delivery['next_try']>time.time():continue
            try:
                message=event['body']
                if time.time()-event['created']>60:
                    message+='\nQueued at '+time.strftime('%d %b %H:%M:%S %Z',time.localtime(event['created']))+'. Delivery was delayed.'
                bot.text(message,chat_id=target['external_id'],disable_notification='true')
                store.recipient_result(key,delivery['recipient'],'sent')
            except RuntimeError as exc:
                store.recipient_result(key,delivery['recipient'],'pending',str(exc),min(300,15*2**min(delivery['attempts'],4)))
        waiting=[d for d in store.recipient_deliveries(key) if d['status']=='pending']
        store.mark_health(event['id'],not waiting,retry_in=15)


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
