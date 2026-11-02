"""Portable runtime choices. Local Mac defaults preserve the current deployment."""
from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import platform


def data_directory(system=None):
    system=system or platform.system()
    if os.environ.get('WATCHYARD_DATA'):
        return Path(os.environ['WATCHYARD_DATA']).expanduser()
    if system=='Darwin':
        return Path.home()/'Library/Application Support/Watchyard'
    return Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'watchyard'


def boolean(name,default):
    value=os.environ.get(name,'1' if default else '0').lower()
    if value not in ('0','1','true','false'):
        raise ValueError(name+' must be 0 or 1')
    return value in ('1','true')


@dataclass(frozen=True)
class Runtime:
    deployment: str
    backend: str
    device: str
    model_override: str
    decoder: str
    host: str
    port: int
    local_bypass: bool
    allowed_hosts: tuple
    allowed_networks: tuple
    proxy_headers: bool
    trusted_proxies: str

    @classmethod
    def read(cls,system=None,machine=None):
        system=system or platform.system()
        machine=machine or platform.machine()
        apple=system=='Darwin' and machine.lower() in ('arm64','aarch64')
        deployment=os.environ.get('WATCHYARD_DEPLOYMENT','local')
        if deployment not in ('local','vps'):
            raise ValueError('WATCHYARD_DEPLOYMENT must be local or vps')
        backend=os.environ.get('WATCHYARD_MODEL_BACKEND','auto')
        if backend=='auto':backend='coreml' if apple else 'pytorch'
        if backend not in ('coreml','pytorch'):
            raise ValueError('WATCHYARD_MODEL_BACKEND must be auto, coreml or pytorch')
        if backend=='coreml' and not apple:
            raise ValueError('Core ML requires an Apple Silicon Mac; use pytorch on Linux')
        decoder=os.environ.get('WATCHYARD_DECODER','auto')
        if decoder=='auto':decoder='videotoolbox' if apple else 'software'
        if decoder not in ('videotoolbox','software') or (decoder=='videotoolbox' and system!='Darwin'):
            raise ValueError('Choose software decoding on Linux')
        gateway=boolean('WATCHYARD_GATEWAY',False)
        host=os.environ.get('WATCHYARD_HOST','127.0.0.1' if gateway or deployment=='vps' else '0.0.0.0')
        port=int(os.environ.get('WATCHYARD_PORT','8766' if gateway else '8765'))
        if not 1<=port<=65535:raise ValueError('Invalid WATCHYARD_PORT')
        hosts=tuple(h.strip().lower() for h in os.environ.get('WATCHYARD_ALLOWED_HOSTS','').split(',') if h.strip())
        networks=tuple(ipaddress.ip_network(n.strip(),strict=False) for n in os.environ.get('WATCHYARD_ALLOWED_CIDRS','').split(',') if n.strip())
        bypass=boolean('WATCHYARD_LOCAL_BYPASS',deployment=='local')
        proxy=boolean('WATCHYARD_PROXY_HEADERS',gateway)
        trusted=os.environ.get('WATCHYARD_TRUSTED_PROXIES','127.0.0.1')
        if deployment=='vps':
            if not hosts or any('*' in h or '://' in h or '/' in h for h in hosts):
                raise ValueError('VPS deployment requires exact WATCHYARD_ALLOWED_HOSTS')
            if not networks or any(n.prefixlen==0 for n in networks):
                raise ValueError('VPS deployment requires restricted WATCHYARD_ALLOWED_CIDRS')
            if bypass:raise ValueError('Loopback authentication bypass is disabled for VPS deployment')
            if proxy and ('*' in trusted or not trusted.strip()):
                raise ValueError('Specify exact trusted proxy addresses on a VPS')
        return cls(deployment,backend,os.environ.get('WATCHYARD_MODEL_DEVICE','cpu'),os.environ.get('WATCHYARD_MODEL_PATH',''),decoder,host,port,bypass,hosts,networks,proxy,trusted)

    def model_path(self,data):
        if self.model_override:
            path=Path(self.model_override).expanduser()
            return path if path.is_absolute() else Path(data)/'models'/path
        return Path(data)/'models'/('yolo11n.mlpackage' if self.backend=='coreml' else 'yolo11n.pt')

    def prediction_options(self):
        return {'device':self.device} if self.backend=='pytorch' else {}
