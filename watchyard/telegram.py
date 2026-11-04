import datetime as dt
import hmac
import json
import logging
import re
import threading
import time

import requests
from .members import Members
from .incidents import AWAY_MINUTES, presence, set_presence


log = logging.getLogger(__name__)
COMMANDS = [
    ('status', 'Camera health and alert controls'),
    ('cameras', 'Choose a camera for a snapshot'),
    ('events', 'Recent activity and replays'),
    ('notifications', 'Manage alerts for this account'),
    ('presence', 'Set home presence for incident simulation'),
    ('help', 'Watchyard help'),
]
CALLBACK = re.compile(
    r'(?:status|unmute|mute:60|notifications:(?:on|off)|snapshot:[0-9]{1,18}'
    r'|review:(?:useful|false_alarm):[0-9a-f]{32})'
)


class TelegramAPIError(RuntimeError):
    def __init__(self, code, retry_after=0):
        super().__init__(f'Telegram API error {code}')
        self.code = code
        self.retry_after = retry_after


def keyboard(rows):
    return {'reply_markup': json.dumps({'inline_keyboard': rows}, ensure_ascii=False)}


def button(label, callback):
    return {'text': label, 'callback_data': callback}


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
            response = requests.post(f'https://api.telegram.org/bot{token}/{method}', data=data, files=files, timeout=timeout, allow_redirects=False)
            payload = response.json()
        except (requests.RequestException, ValueError):
            # Never propagate a requests exception: its URL contains the token.
            raise RuntimeError('Telegram connection unavailable') from None
        if not payload.get('ok'):
            code = payload.get('error_code', response.status_code)
            retry_after = (payload.get('parameters') or {}).get('retry_after', 0)
            raise TelegramAPIError(code, retry_after if type(retry_after) is int and retry_after > 0 else 0)
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

    @staticmethod
    def dashboard_link(label, fragment='activity'):
        from .access import lan_address
        from .runtime import Runtime, boolean

        runtime = Runtime.read()
        hosts = [host for host in runtime.allowed_hosts if host not in ('localhost', '127.0.0.1', 'testserver')]
        host = hosts[0] if hosts else lan_address()
        if ':' in host:
            host = '[' + host + ']'
        port = 8765 if boolean('WATCHYARD_GATEWAY', False) else runtime.port
        return {'text': label, 'url': f'http://{host}:{port}/#{fragment}'}

    def photo(self, image, caption, silent=False, event_id=None, chat_id=None):
        self.members.sync_owner()
        results = []
        event = self.service.store.event(event_id) if event_id and self.service else None
        for target in self._targets(chat_id):
            data = {'chat_id': target['external_id'], 'caption': caption, 'disable_notification': str(silent).lower()}
            if event_id:
                links = [self.dashboard_link('Replay on home Wi-Fi', 'event='+event_id)]
                if event and event.get('activity_group'):
                    links.append(self.dashboard_link('Activity group', 'group='+event['activity_group']))
                rows = [links]
                if target['role'] == 'admin':
                    rows.append([button('Useful alert', 'review:useful:'+event_id),
                                 button('False alarm', 'review:false_alarm:'+event_id)])
                data.update(keyboard(rows))
            results.append(self.call('sendPhoto', data, files={'photo': ('camera.jpg', image, 'image/jpeg')}))
            self.last_send_at = time.time()
        return results[0] if len(results) == 1 else results

    def answer(self, callback, message=None):
        data = {'callback_query_id': callback['id']}
        if message:
            data['text'] = message
        try:
            self.call('answerCallbackQuery', data, timeout=5)
        except RuntimeError:
            # A stale callback must not cause an already applied action to be retried.
            log.debug('Telegram callback acknowledgement unavailable')

    @staticmethod
    def alert_toggle(member):
        return button('Pause my alerts', 'notifications:off') if member['alerts'] else button(
            'Resume my alerts', 'notifications:on')

    def status_controls(self, member):
        rows = [[self.alert_toggle(member)], [self.dashboard_link('Open dashboard', 'home')]]
        if member['role'] == 'admin':
            config = self.settings.snapshot()
            muted = not config['enabled'] or config['muted_until'] > time.time()
            rows.insert(1, [button('Resume home alerts', 'unmute') if muted else
                            button('Mute home alerts for 1 hour', 'mute:60')])
        status = self.service.status_text()
        status += '\nYour Telegram alerts: ' + ('on' if member['alerts'] else 'paused')
        return status, keyboard(rows)

    def refresh_controls(self, message, member):
        old_text = message.get('text', '')
        if old_text.startswith('Watchyard\n'):
            text, options = self.status_controls(member)
        elif old_text.startswith('Your alerts are '):
            text = 'Your alerts are on.' if member['alerts'] else 'Your alerts are paused.'
            options = keyboard([[self.alert_toggle(member)]])
        else:
            return
        if 'message_id' not in message:
            return
        try:
            self.call('editMessageText', {'chat_id': member['external_id'], 'message_id': message['message_id'],
                                          'text': text, **options}, timeout=5)
        except RuntimeError:
            log.debug('Telegram controls message could not be refreshed')

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
                self.text('Watchyard is paired. Use /status, /cameras or /events.', chat_id=chat['id'])
                return
            member=self.members.accept(text.strip().split(maxsplit=1)[1],'telegram',str(chat['id']),client='telegram:'+str(chat['id']))
            if member:
                self.text('This Telegram account is approved for Watchyard. Access: '+member['role']+'. Camera alerts include snapshots. Use /snapshot, /status and /notifications off to pause your alerts.',chat_id=chat['id'])
                return
            if not self.allowed(chat,user):
                self.call('sendMessage',{'chat_id':chat['id'],'text':'This invitation is invalid, expired or already used. Ask the home owner for a new Telegram account invitation, then open it in the intended account and tap Start.'})
                return
        if not self.allowed(chat, user):
            if callback:
                self.answer(callback, 'This account no longer has access.')
            return
        member = self.members.find('telegram', chat['id'])
        self.members.touch(member)

        def reply(message, **extra):
            return self.text(message, chat_id=chat['id'], disable_notification='true', **extra)

        if callback:
            if not CALLBACK.fullmatch(text):
                self.answer(callback, 'This button is no longer available.')
                return
            text = '/'+text.replace(':', ' ')
        parts = text.strip().split()
        if not parts:
            return
        cmd = parts[0].split('@')[0].lower()
        if cmd in ('/mute', '/unmute', '/review', '/presence') and member['role'] != 'admin':
            message = 'Only a home manager can use this control.'
            if callback:
                self.answer(callback, message)
            else:
                reply(message)
            return

        def confirm(message):
            if callback:
                self.answer(callback, message)
            else:
                reply(message)

        if cmd in ('/start', '/help'):
            lines = [f'/{name} — {description}' for name, description in COMMANDS if name not in ('help', 'presence')]
            lines.append('/snapshot [camera ID] — one camera or all cameras')
            if member['role'] == 'admin':
                lines.extend(['/mute [minutes] — pause home alerts (default 60)', '/unmute — resume home alerts',
                              '/presence — view or change presence for simulation'])
            reply('Watchyard commands\n' + '\n'.join(lines))
        elif cmd == '/status':
            if callback:
                self.answer(callback)
            status, options = self.status_controls(member)
            reply(status, **options)
        elif cmd == '/cameras':
            cameras = self.settings.snapshot()['cameras']
            buttons = [button(c['name'][:48], f"snapshot:{c['id']}") for c in cameras]
            reply('Choose a camera for a snapshot.', **keyboard([buttons[i:i+2] for i in range(0, len(buttons), 2)]))
        elif cmd == '/snapshot':
            if callback:
                self.answer(callback)
            if len(parts)>1 and (not parts[1].isascii() or not parts[1].isdigit() or len(parts[1])>18):
                reply('Use /snapshot or /snapshot followed by a camera ID.'); return
            ids = [int(parts[1])] if len(parts)>1 else self.service.cameras
            for camera_id in ids:
                camera = self.service.cameras.get(camera_id)
                if camera is None:
                    reply('Camera unavailable. Use /cameras to choose a current camera.'); continue
                image = camera.jpeg()
                name = self.service.camera_config(camera_id)['name']
                if image:
                    stamp = dt.datetime.fromtimestamp(camera.captured_at).astimezone().strftime('%d %b %H:%M:%S %Z')
                    self.photo(image, f'Live snapshot · {name}\n{stamp}', silent=True,chat_id=chat['id'])
                else:
                    reply(f'{name}: no fresh picture available.')
        elif cmd == '/notifications':
            if len(parts) == 1:
                reply('Your alerts are on.' if member['alerts'] else 'Your alerts are paused.',
                      **keyboard([[self.alert_toggle(member)]]))
                return
            if len(parts) != 2 or parts[1].lower() not in ('on', 'off'):
                reply('Use /notifications on or /notifications off.')
                return
            enabled = parts[1].lower() == 'on'
            self.members.alerts(chat['id'], enabled)
            confirm('Your alerts are on.' if enabled else 'Your alerts are paused. Use /notifications to resume.')
            if callback:
                self.refresh_controls(message, {**member, 'alerts': enabled})
        elif cmd == '/presence':
            instructions = 'Use /presence home, /presence away 1 (or 4, 8, 24 hours), or /presence paused.'
            if len(parts) == 1:
                state = presence(self.settings.snapshot())
            elif len(parts) == 2 and parts[1] in ('home', 'paused'):
                state = set_presence(self.settings, parts[1])
            elif len(parts) == 3 and parts[1] == 'away' and parts[2] in {str(m // 60) for m in AWAY_MINUTES}:
                state = set_presence(self.settings, 'away', int(parts[2]) * 60)
            else:
                reply(instructions)
                return
            mode = {'home': 'At home', 'away': 'Away', 'paused': 'Paused', 'unknown': 'Unknown'}[state['mode']]
            if state['mode'] == 'away':
                until = dt.datetime.fromtimestamp(state['until']).astimezone().strftime('%d %b %H:%M %Z')
                mode += ' until ' + until
            reply(f'Incident simulation: {mode}.\n{instructions}')
        elif cmd == '/mute':
            if len(parts) > 2 or (len(parts) == 2 and not re.fullmatch(r'[0-9]{1,4}', parts[1])):
                reply('Use /mute followed by 1–1440 minutes.')
                return
            minutes = int(parts[1]) if len(parts) == 2 else 60
            if not 1 <= minutes <= 1440:
                reply('Choose a mute duration from 1 to 1440 minutes.')
                return
            self.settings.save({'muted_until': time.time()+60*minutes})
            confirm(f'Home alerts paused for {minutes} minutes.')
            if callback:
                self.refresh_controls(message, member)
        elif cmd == '/unmute':
            self.settings.save({'muted_until': 0, 'enabled': True})
            confirm('Home alerts resumed.')
            if callback:
                self.refresh_controls(message, member)
        elif cmd == '/review' and len(parts) == 3 and parts[1] in ('useful', 'false_alarm'):
            saved = self.service.store.feedback(parts[2], parts[1])
            confirm('Review saved.' if saved else 'That event is no longer in local history.')
        elif cmd == '/events':
            events = self.service.store.recent(5)
            labels = {'car': 'Vehicle', 'person': 'Person', 'dog': 'Dog', 'cat': 'Cat'}
            lines = [f"{dt.datetime.fromtimestamp(e['created']).astimezone():%d %b %H:%M}  "
                     f"{labels.get(e['label'], e['label'])} at {e['camera_name']}" for e in events]
            reply('Recent events\n' + '\n'.join(lines) if lines else 'No recent events.',
                  **keyboard([[self.dashboard_link('Open Activity')]]))
        elif cmd.startswith('/'):
            reply('Use /help for available commands.')

    def poll(self):
        menu_ready = False
        while not self.service.stop.is_set():
            try:
                if not self.username:
                    self.username = self.call('getMe')['username']
                if not menu_ready:
                    menu_ready = True
                    try:
                        self.call('setMyCommands', {'commands': json.dumps([
                            {'command': name, 'description': description} for name, description in COMMANDS
                        ])}, timeout=5)
                    except RuntimeError:
                        log.debug('Telegram command menu unavailable')
                updates = self.call('getUpdates', {'offset':self.offset,'timeout':15,'allowed_updates':'["message","callback_query"]'}, timeout=22)
                self.last_poll_error = None
                for update in updates:
                    try:
                        self.handle(update)
                    except Exception as exc:
                        # Interactive requests may have already sent part of their response.
                        # Skip the update rather than resending photos or applying controls again.
                        log.warning('Telegram command failed (%s)', type(exc).__name__)
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
