"""Interactive local-only secret configuration. Values never printed."""
import getpass
import json
import os
from pathlib import Path
import secrets

data = Path(os.environ.get('WATCHYARD_DATA',str(Path.home()/'Library/Application Support/Watchyard')))
data.mkdir(parents=True,exist_ok=True)
data.chmod(0o700)
path = data/'secrets.json'
values = json.loads(path.read_text()) if path.exists() else {}
for key,label,private in [('NVR_HOST','NVR IP address',False),('NVR_USERNAME','NVR username',False),('NVR_PASSWORD','NVR password',True),('TELEGRAM_BOT_TOKEN','Telegram bot token',True)]:
    value = getpass.getpass(label+' (blank keeps existing): ') if private else input(label+' (blank keeps existing): ')
    if value:
        values[key] = value
if not values.get('TELEGRAM_CHAT_ID'):
    values.setdefault('PAIRING_CODE',secrets.token_hex(8))
fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(fd,'w') as f:
    json.dump(values,f,indent=2)
print('Credentials saved locally with owner-only permissions.')
if values.get('PAIRING_CODE'):
    print('Send this to YOUR bot in a private chat: /start '+values['PAIRING_CODE'])
