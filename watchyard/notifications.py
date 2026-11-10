"""Provider adapters and the durable per-destination notification outbox."""
import datetime as dt
import hashlib
import hmac
import json
import threading
import time
import uuid
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

import requests

from .policy import decision
from .correlation import LABELS, preview
from .health import camera_message
from .telegram import Telegram, TelegramAPIError, keyboard


@dataclass(frozen=True)
class Notice:
    kind: str
    id: str
    created: float
    message: str
    silent: bool = False
    event: dict | None = None


def post(provider, url, **kwargs):
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(url, timeout=(4, 8), allow_redirects=False, **kwargs)
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f'{provider} returned HTTP {response.status_code}')
        return response
    except requests.RequestException:
        raise RuntimeError(f'{provider} connection unavailable') from None


class TelegramProvider:
    name = 'Telegram'

    def __init__(self, bot):
        self.bot = bot

    def targets(self):
        return {r['id']: r['external_id'] for r in self.bot.recipient_devices()}

    def send(self, target, notice, image):
        if notice.event:
            self.bot.photo(image(), notice.message, silent=notice.silent,
                           event_id=notice.id, chat_id=target)
        else:
            options = {'disable_notification': 'true'} if notice.silent else {}
            if notice.kind in ('health', 'test'):
                options.update(keyboard([[Telegram.dashboard_link('Open dashboard', 'home')]]))
            self.bot.text(notice.message, chat_id=target, **options)


class PushoverProvider:
    name = 'Pushover'

    def __init__(self, config):
        self.config = config

    def targets(self):
        user = self.config.get('user_key')
        token = self.config.get('app_token')
        if not all(isinstance(v, str) and v.strip() for v in (user, token)):
            return {}
        key = hashlib.sha256(user.encode()).hexdigest()[:32]
        return {'pushover:' + key: user}

    def send(self, target, notice, image):
        data = {'token': self.config['app_token'], 'user': target, 'title': 'Watchyard',
                'message': notice.message[:1024], 'priority': -1 if notice.silent else 0,
                'timestamp': int(notice.created)}
        if self.config.get('device'):
            data['device'] = self.config['device']
        files = {}
        if notice.event and self.config.get('attach_snapshot') is True:
            photo = image()
            if len(photo) <= 5_242_880:
                files['attachment'] = ('camera.jpg', photo, 'image/jpeg')
        result = post(self.name, 'https://api.pushover.net/1/messages.json', data=data, files=files)
        try:
            if result.json().get('status') == 1:
                return
        except (ValueError, AttributeError):
            pass
        raise RuntimeError('Pushover did not accept the notification')


class WebhookProvider:
    name = 'Custom webhook'

    def __init__(self, config):
        self.config = config

    def targets(self):
        url = self.config.get('url')
        secret = self.config.get('signing_secret')
        if not isinstance(url, str) or not isinstance(secret, str) or len(secret.encode()) < 32:
            return {}
        try:
            parsed = urlsplit(url)
            secure = parsed.scheme == 'https' or (parsed.scheme == 'http' and
                     parsed.hostname in ('127.0.0.1', '::1', 'localhost'))
            if not secure or not parsed.hostname or parsed.username is not None or parsed.fragment:
                return {}
        except ValueError:
            return {}
        key = hashlib.sha256(url.encode()).hexdigest()[:32]
        return {'webhook:' + key: url}

    def send(self, target, notice, image):
        payload = {'version': 1, 'kind': notice.kind, 'id': notice.id,
                   'created_at': notice.created, 'message': notice.message, 'silent': notice.silent}
        if notice.event:
            e = notice.event
            payload['event'] = {'camera_id': e['camera'], 'camera_name': e['camera_name'],
                                'label': e['label'], 'confidence': e['confidence']}
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
        stamp = str(int(time.time()))
        digest = hmac.new(self.config['signing_secret'].encode(), stamp.encode()+b'.'+body,
                          hashlib.sha256).hexdigest()
        post(self.name, target, data=body, headers={
            'Content-Type': 'application/json', 'X-Watchyard-Timestamp': stamp,
            'X-Watchyard-Signature': 'sha256='+digest,
            'Idempotency-Key': notice.kind+':'+notice.id,
        })


class Notifications:
    def __init__(self, settings, bot):
        self.settings = settings
        self.bot = bot
        self.telegram = TelegramProvider(bot)
        self.delivery_lock = threading.Lock()

    def providers(self):
        enabled = self.settings.secret('NOTIFICATION_PROVIDERS', ['telegram'])
        if not isinstance(enabled, list):
            enabled = []
        for key, provider in (
            ('telegram', self.telegram),
            ('pushover', PushoverProvider(self.private_config('PUSHOVER'))),
            ('webhook', WebhookProvider(self.private_config('NOTIFICATION_WEBHOOK'))),
        ):
            yield provider, key in enabled

    def private_config(self, key):
        config = self.settings.secret(key, {})
        return config if isinstance(config, dict) else {}

    def targets(self):
        return {key: (provider, target)
                for provider, enabled in self.providers() if enabled
                for key, target in provider.targets().items()}

    def status(self):
        return [{'name': provider.name, 'enabled': enabled,
                 'destinations': len(provider.targets()) if enabled else 0}
                for provider, enabled in self.providers()]

    def send_test(self, targets):
        notice = Notice('test', uuid.uuid4().hex, time.time(),
                        'Watchyard test notification. Walk through a camera view to test object detection.')
        failures = set()
        sent = 0
        for provider, target in targets.values():
            try:
                provider.send(target, notice, None)
                sent += 1
            except RuntimeError:
                failures.add(provider.name)
        if failures:
            raise RuntimeError(f'Test accepted by {sent} destination(s); failed: '+', '.join(sorted(failures)))

    def attempt(self, store, key, targets, notice, image=None, *, activity_group=None, episode_id=None, camera_batch=None):
        store.ensure_recipients(key, [{'id': target} for target in targets])
        for d in store.recipient_deliveries(key):
            if d['status'] != 'pending':
                continue
            target = targets.get(d['recipient'])
            if not target:
                store.recipient_result(key, d['recipient'], 'cancelled')
                continue
            if d['next_try'] > time.time():
                continue
            provider, address = target
            if (activity_group and provider is self.telegram
                    and store.activity_delivered(activity_group, key, d['recipient'], episode_id, audible=not notice.silent)):
                store.recipient_result(key, d['recipient'], 'grouped')
                continue
            coverage = None
            outbound = notice
            if camera_batch:
                changes = store.camera_health_changes(camera_batch, d['recipient'])
                if changes is None:
                    continue
                if not changes:
                    store.recipient_result(key, d['recipient'], 'cancelled')
                    continue
                coverage = list(changes)
                outbound = replace(notice, message=camera_message(camera_batch['key'], changes))
            try:
                provider.send(address, outbound, image)
                audible = not outbound.silent if outbound.event and provider is self.telegram else None
                store.recipient_result(key, d['recipient'], 'sent', coverage=coverage, audible=audible)
            except (RuntimeError, OSError) as exc:
                error = str(exc) if isinstance(exc, RuntimeError) else 'Snapshot unavailable'
                if provider is self.telegram and hasattr(self.bot, 'last_delivery_error'):
                    self.bot.last_delivery_error = error
                delay = min(300, 15*2**min(d['attempts'],4)) if notice.kind == 'health' else min(60, 5*2**min(d['attempts'],4))
                if isinstance(exc, TelegramAPIError):
                    if exc.code == 403:
                        store.recipient_result(key, d['recipient'], 'cancelled', error)
                        continue
                    delay = max(delay, exc.retry_after)
                store.recipient_result(key, d['recipient'], 'pending', error, delay)
        return store.recipient_deliveries(key)

    def group_for(self, store, event):
        if event['label'] not in LABELS:
            return None
        if event['activity_group']:
            return event['activity_group']
        history = store.correlation_events(before=event['created'])
        for group in preview(history, limit=None, include_single=True):
            for member in group['events']:
                if member['id'] == event['id']:
                    return store.assign_activity_group(event['id'], group['id'], member['reason'])
        return None

    def deliver_once(self, store):
        with self.delivery_lock:
            self.deliver_pending(store)

    def deliver_pending(self, store):
        for event in store.pending():
            key = event['id']
            age = time.time()-event['created']
            if age > 180:
                sent = any(d['status']=='sent' for d in store.recipient_deliveries(key))
                store.mark(key, 'partial' if sent else 'expired', 'Alert expired; retained locally')
                continue
            config = self.settings.snapshot()
            camera = next((c for c in config['cameras'] if c['id']==event['camera']), None)
            mode, reason = decision(config, camera, event['label'], event['created']) if camera else ('off', 'Camera removed')
            if not config['enabled'] or config['muted_until'] > time.time():
                mode, reason = 'off', 'Notifications muted before delivery'
            if mode == 'off':
                store.mark(key, 'recorded', reason)
                continue
            stamp = dt.datetime.fromtimestamp(event['created']).astimezone().strftime('%d %b %H:%M:%S %Z')
            action = 'Moving vehicle' if event['label']=='car' else event['label'].capitalize()+' detected'
            caption = f"{action} · {event['camera_name']}\n{stamp}"
            if age > 15:
                caption += f'\nDelivered {int(age)} seconds after detection.'
            notice = Notice('event', key, event['created'], caption, mode=='silent', event)
            targets = self.targets()
            group = self.group_for(store, event) if any(
                provider is self.telegram for provider, _ in targets.values()
            ) else None
            episode = store.episode_for(key, group) if group else None
            results = self.attempt(store, key, targets, notice,
                                   lambda: (self.settings.path/'events'/event['snapshot']).read_bytes(),
                                   activity_group=group, episode_id=episode)
            waiting = [d for d in results if d['status']=='pending']
            telegram_waiting = [d for d in waiting if targets[d['recipient']][0] is self.telegram]
            self.bot.last_delivery_error = telegram_waiting[0]['error'] if telegram_waiting else None
            sent = sum(d['status']=='sent' for d in results)
            if waiting:
                store.mark(key, 'pending', f'Delivered to {sent}/{len(results)} destinations; retrying: {waiting[0]["error"]}',
                           retry_in=max(1, min(d['next_try'] for d in waiting)-time.time()))
            else:
                grouped = sum(d['status']=='grouped' for d in results)
                status = 'sent' if sent else 'grouped' if grouped else 'recorded'
                detail = f'Delivered to {sent}/{len(results)} destinations' if results else 'No alert destinations enabled'
                if grouped:
                    detail += f'. Already alerted for this activity on {grouped} Telegram destination(s).'
                store.mark(key, status, detail)

    def flush_health(self, store):
        targets = self.targets()
        for event in store.pending_health():
            key = 'health:'+event['id']
            batch = event if event['camera_changes'] else None
            message = event['body']
            if not batch and time.time()-event['created'] > 60:
                message += '\nQueued at '+time.strftime('%d %b %H:%M:%S %Z', time.localtime(event['created']))+'. Delivery was delayed.'
            notice = Notice('health', event['id'], event['created'], message, True)
            results = self.attempt(store, key, targets, notice, camera_batch=batch)
            waiting = [d['next_try'] for d in results if d['status']=='pending']
            if waiting:
                store.mark_health(event['id'], 'pending', retry_in=max(15, min(waiting)-time.time()))
            elif results or batch:
                status = 'sent' if any(d['status']=='sent' for d in results) else 'superseded'
                store.mark_health(event['id'], status)

    def start(self, store, stop):
        def work():
            while not stop.wait(1):
                self.deliver_once(store)
        threading.Thread(target=work, name='notification-delivery', daemon=True).start()
