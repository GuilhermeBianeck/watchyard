"""Generate/reset the Wi-Fi dashboard code locally; also revokes existing sessions."""
import secrets
from watchyard.config import Settings
from watchyard.access import Access

settings = Settings()
settings.save_secrets({'DASHBOARD_SESSION_KEY':secrets.token_hex(32)})
access = Access(settings)
code = ''.join(str(secrets.randbelow(10)) for _ in range(8))
settings.save_secrets({'DASHBOARD_CODE_HASH':access.digest(code)})
print('Dashboard code:',code)
print('Restart Watchyard after resetting an existing code.')
