import datetime as dt
import hmac
import threading
import time

import requests
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
        self.username = None

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
            if event_id:
                from .access import lan_address
                from .runtime import Runtime,boolean
                runtime=Runtime.read()
                hosts=[h for h in runtime.allowed_hosts if h not in ('localhost','127.0.0.1','testserver')]
                host=hosts[0] if hosts else lan_address()
                if ':' in host:host='['+host+']'
                port=8765 if boolean('WATCHYARD_GATEWAY',False) else runtime.port
                keyboard['inline_keyboard'].append([{'text':'Replay on home Wi-Fi','url':f'http://{host}:{port}/#event={event_id}'}])
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
            reply('Watchyard commands\n/status — cameras and detector health\n/snapshot [camera ID] — current picture (all cameras if omitted)\n/events — five recent events\n/notifications on|off — your alerts\n/mute [minutes] — silence alerts (default 60)\n/unmute — resume alerts\n\nSnapshots are sent only to this verified private chat. Detection continues while muted.')
        elif cmd == '/status':
            reply(self.service.status_text())
        elif cmd == '/snapshot':
            if len(parts)>1 and (not parts[1].isascii() or not parts[1].isdigit() or len(parts[1])>18):
                reply('Use /snapshot or /snapshot followed by a camera ID.'); return
            ids = [int(parts[1])] if len(parts)>1 else self.service.cameras
            for camera_id in ids:
                camera = self.service.cameras.get(camera_id)
                if camera is None:
                    reply('Available camera IDs: '+', '.join(map(str,self.service.cameras))+'.'); continue
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
                if not self.username:
                    self.username = self.call('getMe')['username']
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
        self.service.notifications.deliver_once(self.service.store)

    def start(self):
        if self.settings.secret('TELEGRAM_BOT_TOKEN'):
            threading.Thread(target=self.poll,name='telegram-poll',daemon=True).start()
