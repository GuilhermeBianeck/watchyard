import datetime as dt
import hmac
import threading
import time

import requests
from .policy import decision
from .members import Members


class Telegram:
    def __init__(self, settings, service):
        self.settings, self.service = settings, service
        self.members=Members(settings)
        self.offset = settings.snapshot().get('telegram_offset',0)
        self.last_delivery_error = None
        self.last_poll_error = None
        self.last_send_at = 0
        self.last_success = 0
        self.username = "HouseCCTVAlertBot"

    @property
    def last_error(self):
        return self.last_delivery_error or self.last_poll_error

    def call(self, method, data=None, files=None, timeout=20):
        token = self.settings.secret('TELEGRAM_BOT_TOKEN')
        if not token:
            raise RuntimeError('Telegram token not configured')
        try:
            response = requests.post(f'https://api.telegram.org/bot{token}/{method}', data=data, files=files, timeout=timeout)
            payload = response.json()
        except (requests.RequestException, ValueError):
            # Never propagate a requests exception: its URL contains the token.
            raise RuntimeError('Telegram connection unavailable') from None
        if not payload.get('ok'):
            code = payload.get('error_code', response.status_code)
            raise RuntimeError(f'Telegram API error {code}')
        self.last_success = time.time()
        return payload.get('result')

    def recipient_devices(self):
        return self.members.recipients(alerts_only=True)

    def paired(self):
        return bool(self.members.recipients())

    def allowed(self,chat,user):
        self.members.sync_owner()
        if chat.get('type')!='private' or not isinstance(chat.get('id'),int) or chat['id']<=0 or chat.get('id')!=user.get('id'):return False
        return self.members.active(self.members.find('telegram',chat.get('id')))

    def _targets(self,chat_id):
        if chat_id is None:return self.recipient_devices()
        target=self.members.find('telegram',chat_id)
        if not self.members.active(target):raise RuntimeError('Telegram account is no longer approved')
        return [target]

    def text(self,message,chat_id=None,**extra):
        self.members.sync_owner()
        results=[]
        for target in self._targets(chat_id):
            results.append(self.call('sendMessage',{'chat_id':target['external_id'],'text':message,**extra}))
            self.last_send_at=time.time()
        return results[0] if len(results)==1 else results

    def photo(self,image,caption,silent=False,event_id=None,chat_id=None):
        import json
        self.members.sync_owner()
        results=[]
        for target in self._targets(chat_id):
            keyboard={'inline_keyboard':[[{'text':'Status','callback_data':'status'},{'text':'Pause my alerts','callback_data':'notifications:off'}]]}
            if target['role']=='admin':
                keyboard['inline_keyboard'][0].append({'text':'Mute home 1 hour','callback_data':'mute:60'})
                if event_id:keyboard['inline_keyboard'].append([{'text':'Useful alert','callback_data':'review:useful:'+event_id},{'text':'False alarm','callback_data':'review:false_alarm:'+event_id}])
            results.append(self.call('sendPhoto',{'chat_id':target['external_id'],'caption':caption,'disable_notification':str(silent).lower(),'reply_markup':json.dumps(keyboard)},files={'photo':('camera.jpg',image,'image/jpeg')}))
            self.last_send_at=time.time()
        return results[0] if len(results)==1 else results

    def handle(self, update):
        message = update.get('message', {})
        callback = update.get('callback_query')
        if callback:
            message = callback.get('message', {})
        chat = message.get('chat', {})
        user = callback.get('from', {}) if callback else message.get('from', {})
        text = callback.get('data', '') if callback else message.get('text', '')
        private=chat.get('type')=='private' and isinstance(chat.get('id'),int) and chat['id']>0 and chat.get('id')==user.get('id')
        if private and not callback and text.strip().startswith('/start '):
            code=self.settings.secret('PAIRING_CODE','')
            if not self.paired() and code and hmac.compare_digest(text.strip().encode(),('/start '+code).encode()):
                self.settings.save_secrets({'TELEGRAM_CHAT_ID':chat['id'],'PAIRING_CODE':''})
                self.members.sync_owner()
                self.text('Watchyard is paired with this private chat. Use /status, /snapshot, /events or /help.')
                return
            member=self.members.accept(text.strip().split(maxsplit=1)[1],'telegram',str(chat['id']),client='telegram:'+str(chat['id']))
            if member:
                self.text('This Telegram account is approved for Watchyard. Access: '+member['role']+'. Camera alerts include snapshots. Use /snapshot, /status and /notifications off to pause your alerts.',chat_id=chat['id'])
                return
            if not self.allowed(chat,user):
                self.call('sendMessage',{'chat_id':chat['id'],'text':'This invitation is invalid, expired or already used. Ask the home owner for a new Telegram account invitation, then open it in the intended account and tap Start.'})
                return
        if not self.allowed(chat, user):
            return
        member=self.members.find('telegram',chat['id'])
        self.members.touch(member)
        def reply(message,**extra):return self.text(message,chat_id=chat['id'],**extra)
        if callback:
            self.call('answerCallbackQuery', {'callback_query_id':callback['id']})
            text = '/'+text.replace(':', ' ')
        parts = text.strip().split()
        if not parts:
            return
        cmd = parts[0].split('@')[0].lower()
        if cmd in ('/mute','/unmute','/review') and member['role']!='admin':
            reply('This account has view-only access. Use /notifications off to pause only your alerts.');return
        if cmd in ('/start','/help'):
            reply('Watchyard commands\n/status — cameras and detector health\n/snapshot [1–4] — current picture (all four if omitted)\n/events — five recent events\n/notifications on|off — your alerts\n/mute [minutes] — silence alerts (default 60)\n/unmute — resume alerts\n\nSnapshots are sent only to this verified private chat. Detection continues while muted.')
        elif cmd == '/status':
            reply(self.service.status_text())
        elif cmd == '/snapshot':
            ids = [int(parts[1])] if len(parts)>1 and parts[1].isdigit() else [1,2,3,4]
            for camera_id in ids:
                camera = self.service.cameras.get(camera_id)
                if camera is None:
                    reply('Camera must be 1–4.'); continue
                image = camera.jpeg()
                name = self.service.camera_config(camera_id)['name']
                if image:
                    stamp = dt.datetime.fromtimestamp(camera.captured_at).astimezone().strftime('%d %b %H:%M:%S %Z')
                    self.photo(image, f'Live snapshot · {name}\n{stamp}', silent=True,chat_id=chat['id'])
                else:
                    reply(f'{name}: no fresh picture available.')
        elif cmd == '/notifications':
            enabled=len(parts)<2 or parts[1].lower()!='off'
            self.members.alerts(chat['id'],enabled)
            reply('Your alerts are '+('enabled.' if enabled else 'paused. Use /notifications on to resume.'))
        elif cmd == '/mute':
            minutes = int(parts[1]) if len(parts)>1 and parts[1].isdigit() else 60
            minutes = max(1,min(minutes,1440))
            self.settings.save({'muted_until':time.time()+minutes*60})
            reply(f'Alerts muted for {minutes} minutes. Detection and event history continue.')
        elif cmd == '/unmute':
            self.settings.save({'muted_until':0, 'enabled':True})
            reply('Alerts resumed.')
        elif cmd == '/review' and len(parts)==3 and parts[1] in ('useful','false_alarm'):
            saved = self.service.store.feedback(parts[2],parts[1])
            reply('Review saved.' if saved else 'That event is no longer in local history.',disable_notification='true')
        elif cmd == '/events':
            events = self.service.store.recent(5)
            reply('\n'.join(f"{dt.datetime.fromtimestamp(e['created']).astimezone():%H:%M} · {e['label']} · {e['camera_name']} · {e['status']}" for e in events) if events else 'No confirmed events yet. Try walking through a camera view.')

    def poll(self):
        while not self.service.stop.is_set():
            try:
                updates = self.call('getUpdates', {'offset':self.offset,'timeout':15,'allowed_updates':'["message","callback_query"]'}, timeout=22)
                self.last_poll_error = None
                for update in updates:
                    # Advance after handling. Retried commands are harmless/idempotent.
                    self.handle(update)
                    self.offset = update['update_id']+1
                    self.settings.save({'telegram_offset':self.offset})
            except Exception as exc:
                self.last_poll_error = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
                self.service.stop.wait(5)

    def deliver_once(self):
        if not self.paired():return
        for event in self.service.store.pending():
            store=self.service.store
            if time.time()-event['created']>180:
                sent=sum(d['status']=='sent' for d in store.recipient_deliveries(event['id']))
                store.mark(event['id'],'partial' if sent else 'expired','Some recipients missed the alert' if sent else 'Notification older than three minutes; retained locally')
                continue
            config=self.settings.snapshot()
            camera=next(c for c in config['cameras'] if c['id']==event['camera'])
            mode,reason=decision(config,camera,event['label'],event['created'])
            if not config['enabled'] or config['muted_until']>time.time():mode,reason='off','Notifications muted before delivery'
            if mode=='off':store.mark(event['id'],'recorded',reason);continue
            recipients={r['id']:r for r in self.recipient_devices()}
            store.ensure_recipients(event['id'],list(recipients.values()))
            deliveries=store.recipient_deliveries(event['id'])
            if not deliveries:
                store.mark(event['id'],'recorded','No Telegram accounts have alerts enabled');continue
            for d in deliveries:
                if d['status']!='pending':continue
                target=recipients.get(d['recipient'])
                if not target:
                    store.recipient_result(event['id'],d['recipient'],'cancelled');continue
                if d['next_try']>time.time():continue
                try:
                    image=(self.settings.path/'events'/event['snapshot']).read_bytes()
                    stamp=dt.datetime.fromtimestamp(event['created']).astimezone().strftime('%d %b %H:%M:%S %Z')
                    action='Moving vehicle' if event['label']=='car' else event['label'].capitalize()+' detected'
                    caption=f"{action} · {event['camera_name']}\n{stamp}\nConfirmed across multiple frames."
                    age=time.time()-event['created']
                    if age>15:caption+=f'\nDelayed delivery: {int(age)} seconds.'
                    self.photo(image,caption,silent=mode=='silent',event_id=event['id'],chat_id=target['external_id'])
                    store.recipient_result(event['id'],d['recipient'],'sent')
                except Exception as exc:
                    error=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
                    self.last_delivery_error=error
                    store.recipient_result(event['id'],d['recipient'],'pending',error,min(60,5*2**min(d['attempts'],4)))
            results=store.recipient_deliveries(event['id'])
            waiting=[d for d in results if d['status']=='pending']
            sent=sum(d['status']=='sent' for d in results)
            if waiting:
                self.last_delivery_error=waiting[0]['error'] or 'Delivery pending'
                store.mark(event['id'],'pending',f'Delivered to {sent}/{len(results)} accounts; retrying',retry_in=max(1,min(d['next_try'] for d in waiting)-time.time()))
            else:
                self.last_delivery_error=None
                store.mark(event['id'],'sent' if sent else 'recorded',f'Delivered to {sent} account(s)' if sent else 'Recipients revoked or paused')

    def deliver(self):
        while not self.service.stop.wait(1):
            self.deliver_once()

    def start(self):
        threading.Thread(target=self.poll,name='telegram-poll',daemon=True).start()
        threading.Thread(target=self.deliver,name='telegram-delivery',daemon=True).start()
