"""Home-network access with code pairing and signed, HttpOnly sessions."""
import hashlib
import hmac
import ipaddress
import secrets
import socket
import threading
import time
import psutil
from .runtime import Runtime


def lan_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('192.168.1.43', 80))
            return sock.getsockname()[0]
    except OSError:
        return '127.0.0.1'


def lan_network(address):
    for entries in psutil.net_if_addrs().values():
        for entry in entries:
            if entry.family == socket.AF_INET and entry.address == address and entry.netmask:
                return ipaddress.ip_network(address+'/'+entry.netmask, strict=False)
    return ipaddress.ip_network(address+'/32', strict=False)


class Access:
    cookie = 'watchyard_session'

    def __init__(self, settings):
        self.settings = settings
        self.runtime = Runtime.read()
        if not settings.secret('DASHBOARD_SESSION_KEY'):
            settings.save_secrets({'DASHBOARD_SESSION_KEY': secrets.token_hex(32)})
        self.key = bytes.fromhex(settings.secret('DASHBOARD_SESSION_KEY'))
        self.attempts = {}
        self.lock = threading.Lock()

    @staticmethod
    def local(client):
        return client in ('127.0.0.1', '::1', 'testclient')

    def digest(self, value):
        return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()

    def authenticated(self, request):
        if self.runtime.local_bypass and self.local(request.client.host):
            return True
        token = request.cookies.get(self.cookie, '')
        try:
            expiry, nonce, signature = token.split('.')
            return int(expiry) > time.time() and hmac.compare_digest(signature, self.digest(expiry+'.'+nonce))
        except (ValueError, TypeError):
            return False

    def login(self, code, client):
        now = time.time()
        with self.lock:
            # Bound memory and limit attempts by client plus a global limit.
            self.attempts = {k:[t for t in v if now-t<300] for k,v in self.attempts.items() if v and now-v[-1]<300}
            if len(self.attempts.get(client, [])) >= 5 or sum(map(len,self.attempts.values())) >= 30:
                return None, 429
            expected = self.settings.secret('DASHBOARD_CODE_HASH', '')
            if not expected or not hmac.compare_digest(self.digest(code), expected):
                self.attempts.setdefault(client, []).append(now)
                return None, 401
            self.attempts.pop(client, None)
        value = str(int(now+30*86400))+'.'+secrets.token_hex(16)
        return value+'.'+self.digest(value), 200
