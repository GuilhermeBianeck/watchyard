import datetime as dt
import hmac
import threading
import time

import requests
from .policy import decision


class Telegram:
    def __init__(self, settings, service):
        self.settings, self.service = settings, service
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

    def paired(self):
        return self.settings.secret('TELEGRAM_CHAT_ID') is not None

    def allowed(self, chat, user):
        target = self.settings.secret('TELEGRAM_CHAT_ID')
        return target is not None and chat.get('type') == 'private' and chat.get('id') == target and user.get('id') == target

    def text(self, message, **extra):
        result = self.call('sendMessage', {'chat_id':self.settings.secret('TELEGRAM_CHAT_ID'), 'text':message, **extra})
        self.last_send_at = time.time()
        return result

    def photo(self, image, caption, silent=False, event_id=None):
        import json
        keyboard = {'inline_keyboard': [[{'text':'Mute 1 hour','callback_data':'mute:60'}, {'text':'Status','callback_data':'status'}]]}
        if event_id:
            keyboard['inline_keyboard'].append([{'text':'Useful alert','callback_data':'review:useful:'+event_id},{'text':'False alarm','callback_data':'review:false_alarm:'+event_id}])
        result = self.call('sendPhoto', {'chat_id':self.settings.secret('TELEGRAM_CHAT_ID'), 'caption':caption, 'disable_notification':str(silent).lower(), 'reply_markup':json.dumps(keyboard)}, files={'photo':('camera.jpg',image,'image/jpeg')})
        self.last_send_at = time.time()
        self.last_delivery_error = None
        return result

    def handle(self, update):
        message = update.get('message', {})
        callback = update.get('callback_query')
        if callback:
            message = callback.get('message', {})
        chat = message.get('chat', {})
        user = callback.get('from', {}) if callback else message.get('from', {})
        text = callback.get('data', '') if callback else message.get('text', '')
        if not self.paired():
            code = self.settings.secret('PAIRING_CODE', '')
            if not callback and code and chat.get('type') == 'private' and chat.get('id') == user.get('id') and hmac.compare_digest(text.strip(), '/start '+code):
                self.settings.save_secrets({'TELEGRAM_CHAT_ID':chat['id'], 'PAIRING_CODE':''})
                self.text('Watchyard is paired with this private chat. Camera analysis is starting. Use /status, /snapshot, /mute 60, /unmute or /help. Animal alerts are silent. Pictures requested here pass through Telegram.')
            return
        if not self.allowed(chat, user):
            return
        if callback:
            self.call('answerCallbackQuery', {'callback_query_id':callback['id']})
            text = '/'+text.replace(':', ' ')
        parts = text.strip().split()
        if not parts:
            return
        cmd = parts[0].split('@')[0].lower()
        if cmd in ('/start','/help'):
            self.text('Watchyard commands\n/status — cameras and detector health\n/snapshot [1–4] — current picture (all four if omitted)\n/events — five recent events\n/mute [minutes] — silence alerts (default 60)\n/unmute — resume alerts\n\nSnapshots are sent only to this verified private chat. Detection continues while muted.')
        elif cmd == '/status':
            self.text(self.service.status_text())
        elif cmd == '/snapshot':
            ids = [int(parts[1])] if len(parts)>1 and parts[1].isdigit() else [1,2,3,4]
            for camera_id in ids:
                camera = self.service.cameras.get(camera_id)
                if camera is None:
                    self.text('Camera must be 1–4.'); continue
                image = camera.jpeg()
                name = self.service.camera_config(camera_id)['name']
                if image:
                    stamp = dt.datetime.fromtimestamp(camera.captured_at).astimezone().strftime('%d %b %H:%M:%S %Z')
                    self.photo(image, f'Live snapshot · {name}\n{stamp}', silent=True)
                else:
                    self.text(f'{name}: no fresh picture available.')
        elif cmd == '/mute':
            minutes = int(parts[1]) if len(parts)>1 and parts[1].isdigit() else 60
            minutes = max(1,min(minutes,1440))
            self.settings.save({'muted_until':time.time()+minutes*60})
            self.text(f'Alerts muted for {minutes} minutes. Detection and event history continue.')
        elif cmd == '/unmute':
            self.settings.save({'muted_until':0, 'enabled':True})
            self.text('Alerts resumed.')
        elif cmd == '/review' and len(parts)==3 and parts[1] in ('useful','false_alarm'):
            saved = self.service.store.feedback(parts[2],parts[1])
            self.text('Review saved.' if saved else 'That event is no longer in local history.',disable_notification='true')
        elif cmd == '/events':
            events = self.service.store.recent(5)
            self.text('\n'.join(f"{dt.datetime.fromtimestamp(e['created']).astimezone():%H:%M} · {e['label']} · {e['camera_name']} · {e['status']}" for e in events) if events else 'No confirmed events yet. Try walking through a camera view.')

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
        if not self.paired():
            return
        for event in self.service.store.pending():
            age = time.time()-event['created']
            if age > 180:
                self.service.store.mark(event['id'],'expired','Event retained locally; notification older than three minutes')
                continue
            config = self.settings.snapshot()
            camera = next(c for c in config['cameras'] if c['id']==event['camera'])
            mode,reason = decision(config,camera,event['label'],event['created'])
            if not config['enabled'] or config['muted_until'] > time.time():
                mode,reason = 'off','Notifications muted before delivery'
            if mode=='off':
                self.service.store.mark(event['id'],'recorded',reason)
                continue
            try:
                image = (self.settings.path/'events'/event['snapshot']).read_bytes()
                stamp = dt.datetime.fromtimestamp(event['created']).astimezone().strftime('%d %b %H:%M:%S %Z')
                action = 'Moving vehicle' if event['label']=='car' else event['label'].capitalize()+' detected'
                caption = f"{action} · {event['camera_name']}\n{stamp}\nConfirmed across multiple frames."
                if age > 15:
                    caption += f'\nDelayed delivery: {int(age)} seconds.'
                self.photo(image,caption,silent=mode=='silent',event_id=event['id'])
                self.last_delivery_error = None
                self.service.store.mark(event['id'],'sent')
            except Exception as exc:
                self.last_delivery_error = str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
                self.service.store.mark(event['id'],'pending',self.last_delivery_error,retry_in=min(60,5*2**min(event['attempts'],4)))

    def deliver(self):
        while not self.service.stop.wait(1):
            self.deliver_once()

    def start(self):
        threading.Thread(target=self.poll,name='telegram-poll',daemon=True).start()
        threading.Thread(target=self.deliver,name='telegram-delivery',daemon=True).start()
