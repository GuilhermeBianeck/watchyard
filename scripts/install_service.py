"""Install current source into a persistent runtime and a per-user LaunchAgent."""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

if sys.platform != 'darwin':
    raise SystemExit('Use deploy/vps/compose.yaml on Linux; this installer is macOS-only.')

root = Path(__file__).resolve().parents[1]
data = Path(os.environ.get('WATCHYARD_DATA',str(Path.home()/'Library/Application Support/Watchyard')))
data.mkdir(parents=True,exist_ok=True)
data.chmod(0o700)
runtime = data/'runtime'
dev = root/'.venv'
if not runtime.exists():
    if dev.exists() and not dev.is_symlink():
        shutil.move(str(dev),str(runtime))
        dev.symlink_to(runtime,target_is_directory=True)
    else:
        subprocess.run([sys.executable,'-m','venv',str(runtime)],check=True)
        subprocess.run([str(runtime/'bin/python'),'-m','pip','install',str(root)],check=True)
python = runtime/'bin/python'
subprocess.run([str(python),'-m','pip','install','--no-deps','--no-build-isolation','--force-reinstall',str(root)],check=True)
subprocess.run([str(python),'-c','from watchyard.config import Settings; from watchyard.store import Store; Store(Settings().path)'],check=True)
if subprocess.check_output([str(python), '-c',
        "from watchyard.config import Settings; print(any(c.get('plate_zone') for c in Settings().snapshot()['cameras']))"
        ], env=os.environ | {'WATCHYARD_DATA': str(data)}).strip() == b'True':
    plate_helper = runtime/'plate-ocr'
    staged = runtime/'plate-ocr.new'
    subprocess.run(['swiftc', '-O', str(root/'scripts/plate_ocr.swift'), '-o', str(staged)], check=True)
    staged.replace(plate_helper)
logs = data/'logs'; logs.mkdir(exist_ok=True)
gateway = data/'gateway.cjs'
shutil.copyfile(root/'watchyard/gateway.cjs',gateway)
node = shutil.which('node')
if not node:
    raise RuntimeError('Node.js is required for the home-network web gateway.')
agents = Path.home()/'Library/LaunchAgents'; agents.mkdir(exist_ok=True)
plist = agents/'com.watchyard.server.plist'
payload = {
    'Label':'com.watchyard.server',
    'ProgramArguments':['/usr/bin/caffeinate','-i','-s',str(python),'-m','watchyard.app'],
    'WorkingDirectory':str(data),
    'EnvironmentVariables':{'PATH':'/opt/homebrew/bin:/usr/bin:/bin','WATCHYARD_DATA':str(data),'TZ':'Europe/Lisbon','PYTHONUNBUFFERED':'1','YOLO_AUTOINSTALL':'false','OMP_NUM_THREADS':'2','WATCHYARD_GATEWAY':'1'},
    'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':15,
    'StandardOutPath':str(logs/'server.log'),'StandardErrorPath':str(logs/'server-error.log'),
    'ProcessType':'Background',
}
plist.write_bytes(plistlib.dumps(payload))
target=f'gui/{os.getuid()}'
subprocess.run(['launchctl','bootout',target,str(plist)],capture_output=True)
gateway_plist = agents/'com.watchyard.gateway.plist'
gateway_payload = {
    'Label':'com.watchyard.gateway', 'ProgramArguments':[node,str(gateway)],
    'WorkingDirectory':str(data), 'RunAtLoad':True, 'KeepAlive':True, 'ThrottleInterval':15,
    'StandardOutPath':str(logs/'gateway.log'), 'StandardErrorPath':str(logs/'gateway-error.log'),
}
gateway_plist.write_bytes(plistlib.dumps(gateway_payload))
subprocess.run(['launchctl','bootout',target,str(gateway_plist)],capture_output=True)
subprocess.run(['launchctl','bootstrap',target,str(plist)],check=True)
subprocess.run(['launchctl','bootstrap',target,str(gateway_plist)],check=True)
watchdog_plist = agents/'com.watchyard.watchdog.plist'
watchdog_payload = {
    'Label':'com.watchyard.watchdog','ProgramArguments':[str(python),'-m','watchyard.watchdog'],
    'WorkingDirectory':str(data),'EnvironmentVariables':payload['EnvironmentVariables'],
    'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':15,
    'StandardOutPath':str(logs/'watchdog.log'),'StandardErrorPath':str(logs/'watchdog-error.log'),
}
watchdog_plist.write_bytes(plistlib.dumps(watchdog_payload))
subprocess.run(['launchctl','bootout',target,str(watchdog_plist)],capture_output=True)
subprocess.run(['launchctl','bootstrap',target,str(watchdog_plist)],check=True)
print('Installed Watchyard services. Dashboard: http://127.0.0.1:8765')
