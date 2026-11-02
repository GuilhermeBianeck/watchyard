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
from .members import Members


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
        self.members = Members(settings)
        self.attempts = {}
        self.lock = threading.Lock()

    @staticmethod
    def local(client):
        return client in ('127.0.0.1', '::1', 'testclient')

    def digest(self, value):
        return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()

    def principal(self, request):
        if self.runtime.local_bypass and self.local(request.client.host):
            return {'id':'local','name':'This Mac','role':'admin','kind':'browser'}
        token = request.cookies.get(self.cookie,'')
        try:
            expiry,nonce,signature = token.split('.')
            if int(expiry)<=time.time() or not hmac.compare_digest(signature,self.digest(expiry+'.'+nonce)):
                return None
        except (ValueError,TypeError):
            return None
        digest=self.digest(token)
        device=self.members.find('browser',digest)
        if device is None and not nonce.startswith('d_'):
            # Import existing signed sessions once; new tokens require registry entries.
            device=self.members.register('browser',digest,'Previously signed-in device','admin',float(expiry))
        if not self.members.active(device):return None
        self.members.touch(device)
        return {k:device[k] for k in ('id','name','role','kind')}

    def authenticated(self, request):
        return self.principal(request) is not None

    def login(self, code, client, name="New browser"):
        now = time.time()
        with self.lock:
            # Bound memory and limit attempts by client plus a global limit.
            self.attempts = {k:[t for t in v if now-t<300] for k,v in self.attempts.items() if v and now-v[-1]<300}
            if len(self.attempts.get(client, [])) >= 5 or sum(map(len,self.attempts.values())) >= 30:
                return None, 429
            expected = self.settings.secret('DASHBOARD_CODE_HASH', '')
            owner = bool(expected and hmac.compare_digest(self.digest(code),expected))
        expiry=int(now+30*86400)
        value=str(expiry)+'.d_'+secrets.token_hex(16)
        token=value+'.'+self.digest(value)
        digest=self.digest(token)
        if owner:
            self.members.register('browser',digest,name,'admin',expiry)
        elif not self.members.accept(code,'browser',digest,expiry,client='browser:'+client):
            with self.lock:self.attempts.setdefault(client,[]).append(now)
            return None,401
        with self.lock:self.attempts.pop(client,None)
        return token,200
