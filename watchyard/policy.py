"""Notification decisions, independent from object detection."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

MODES={'person':'normal','car':'normal','dog':'silent','cat':'silent'}
DEFAULT_SCHEDULE={'enabled':False,'days':list(range(7)),'start':'22:00','end':'07:00','timezone':'Europe/Lisbon'}


def scheduled(camera,timestamp):
    rule=camera.get('schedule',DEFAULT_SCHEDULE)
    if not rule.get('enabled',False):
        return True
    local=datetime.fromtimestamp(timestamp,ZoneInfo(rule.get('timezone','Europe/Lisbon')))
    minute=local.hour*60+local.minute
    start=sum(int(v)*m for v,m in zip(rule['start'].split(':'),(60,1)))
    end=sum(int(v)*m for v,m in zip(rule['end'].split(':'),(60,1)))
    days=rule['days']
    if start==end:
        return local.weekday() in days
    if start<end:
        return local.weekday() in days and start<=minute<end
    # A Monday overnight window ends on Tuesday morning.
    return (minute>=start and local.weekday() in days) or (minute<end and (local-timedelta(days=1)).weekday() in days)


def decision(config,camera,label,timestamp):
    if not config['enabled'] or config['muted_until']>timestamp:
        return 'off','Alerts muted'
    mode=camera.get('alert_modes',MODES).get(label,MODES.get(label,'off'))
    if mode=='off':
        return 'off','Category saved locally'
    if not scheduled(camera,timestamp):
        return 'off','Outside alert schedule'
    return mode,''
