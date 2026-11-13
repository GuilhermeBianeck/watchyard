"""Delayed second-view evidence must reduce repeats without hiding arrivals."""
import json

import pytest

from watchyard.config import Settings
from watchyard.correlation import corroborated_person_group
from watchyard.service import Service


def observation(key, camera, start, end, point, colors, group=None):
    return dict(id=key, camera=camera, camera_name=f'Camera {camera}', created=start,
                first_seen=start, last_seen=end, label='person', confidence=.9,
                snapshot='test.jpg', status='recorded', activity_group=group,
                correlation_hint=json.dumps({'point': point, 'entry': point, 'colors': colors}))


def scene(now=10000):
    red = [.9, .1] + [0.0]*14
    shaded = [.3, .7] + [0.0]*14
    turning = [.5, .5] + [0.0]*14
    history = []
    for i, start in enumerate((now-1600, now-1200, now-800)):
        key = f'route-{i}'
        history.extend([
            observation(key, 1, start, start+4, [.4, .65], red, key),
            observation(f'peer-{i}', 3, start+1, start+5, [.3, .8], red, key),
        ])
    history.extend([
        observation('old', 1, now-100, now-95, [.4, .65], red, 'old'),
        observation('recent', 3, now-30, now-25, [.3, .8], shaded, 'old'),
    ])
    current = observation('new', 1, now, now+2.5, [.405, .655], red)
    peer = observation('corroborating', 3, now+1.5, now+5, [.31, .8], turning)
    return current, peer, history


def test_another_camera_can_corroborate_a_return_after_the_blind_gap():
    current, peer, history = scene()
    assert corroborated_person_group(current, history) == (None, True)
    assert corroborated_person_group(current, history+[peer]) == ('old', True)


@pytest.mark.parametrize('change', ['no_route', 'late', 'not_simultaneous', 'wrong_area',
                                  'wrong_colour', 'timing_only', 'no_recent_activity',
                                  'same_view_person', 'peer_view_person', 'vehicle', 'false_alarm'])
def test_insufficient_or_conflicting_evidence_never_suppresses_a_new_alert(change):
    current, peer, history = scene()
    if change == 'no_route':
        history = history[6:]
    elif change == 'late':
        peer['created'] = current['created'] + 4.01
    elif change == 'not_simultaneous':
        peer['first_seen'] = current['last_seen'] + .1
    elif change == 'wrong_area':
        hint = json.loads(peer['correlation_hint'])
        hint['point'] = [.95, .1]
        peer['correlation_hint'] = json.dumps(hint)
    elif change == 'wrong_colour':
        hint = json.loads(current['correlation_hint'])
        hint['colors'] = [0.0]*6+[1.0]+[0.0]*9
        current['correlation_hint'] = json.dumps(hint)
    elif change == 'timing_only':
        # A persisted weak link is not independent corroboration.
        peer['activity_group'] = 'old'
        history[-1]['first_seen'] -= 25
        history[-1]['last_seen'] -= 25
        history[-1]['correlation_hint'] = '{}'
    elif change == 'no_recent_activity':
        history[-1]['last_seen'] = current['created'] - 70
        history[-1]['first_seen'] = current['created'] - 75
    elif change in ('same_view_person', 'peer_view_person'):
        extra = dict(current if change == 'same_view_person' else peer)
        extra.update(id='another-person', activity_group='another-person')
        history.append(extra)
    elif change == 'vehicle':
        current['label'] = 'car'
    elif change == 'false_alarm':
        peer['feedback'] = 'false_alarm'
    assert corroborated_person_group(current, history+[peer])[0] is None


def test_two_independently_corroborated_groups_are_ambiguous():
    current, peer, history = scene()
    other_history = []
    for row in history[-2:]:
        other = dict(row, id='second-'+row['id'], activity_group='second')
        other['first_seen'] -= 4
        other['last_seen'] -= 4
        other['created'] -= 4
        other_history.append(other)
    peer['activity_group'] = 'old'
    other_peer = dict(peer, id='second-peer', activity_group='second')
    assert corroborated_person_group(current, history+other_history+[peer, other_peer])[0] is None


def insert(store, row, **extra):
    row = row | extra
    with store.db:
        store.db.execute(f"INSERT INTO events ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                         list(row.values()))


def prepared_service(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    settings.save_secrets({'TELEGRAM_CHAT_ID': 123})
    service = Service(settings)
    (tmp_path/'events'/'test.jpg').write_bytes(b'image')
    calls = []
    service.telegram.photo = lambda *args, **kwargs: calls.append(kwargs)
    current, peer, history = scene()
    for row in history:
        insert(service.store, row, status='pending' if row['id'] == 'old' else 'recorded')
    monkeypatch.setattr('time.time', lambda: current['created']-100)
    service.notifications.deliver_once(service.store)
    assert [call['event_id'] for call in calls] == ['old']
    monkeypatch.setattr('time.time', lambda: current['created'])
    insert(service.store, current, status='pending')
    return service, calls, current, peer


def test_repeat_wait_survives_restart_and_joins_later_confirmed_view(tmp_path, monkeypatch):
    service, calls, current, peer = prepared_service(tmp_path, monkeypatch)
    service.notifications.deliver_once(service.store)
    waiting = service.store.event('new')
    assert waiting['activity_group'] is None
    assert waiting['attempts'] == 0
    assert waiting['next_try'] == current['created'] + 4
    assert len(calls) == 1
    restarted = Service(service.settings)
    restarted.telegram.photo = lambda *args, **kwargs: calls.append(kwargs)
    insert(restarted.store, peer, status='pending')
    monkeypatch.setattr('time.time', lambda: current['created']+4)
    restarted.notifications.deliver_once(restarted.store)
    assert len(calls) == 1
    assert restarted.store.event('new')['status'] == 'grouped'
    assert restarted.store.event('new')['activity_group'] == 'old'
    assert restarted.store.event('corroborating')['status'] == 'grouped'


def test_no_corroboration_sends_once_at_the_original_deadline(tmp_path, monkeypatch):
    service, calls, current, _ = prepared_service(tmp_path, monkeypatch)
    service.notifications.deliver_once(service.store)
    for offset in (1, 3.9):
        monkeypatch.setattr('time.time', lambda offset=offset: current['created']+offset)
        service.notifications.deliver_once(service.store)
        assert len(calls) == 1
    monkeypatch.setattr('time.time', lambda: current['created']+4)
    service.notifications.deliver_once(service.store)
    service.notifications.deliver_once(service.store)
    assert [call['event_id'] for call in calls] == ['old', 'new']
    assert service.store.event('new')['status'] == 'sent'


def test_camera_check_does_not_delay_other_notification_providers(tmp_path, monkeypatch):
    from types import SimpleNamespace

    service, calls, current, _ = prepared_service(tmp_path, monkeypatch)
    outgoing = []
    provider = SimpleNamespace(send=lambda *args: outgoing.append(args[1].id))
    telegram_targets = service.notifications.targets()
    monkeypatch.setattr(service.notifications, 'targets',
                        lambda: telegram_targets | {'webhook:test': (provider, 'test')})
    service.notifications.deliver_once(service.store)
    assert outgoing == ['new']
    assert len(calls) == 1
    monkeypatch.setattr('time.time', lambda: current['created']+4)
    service.notifications.deliver_once(service.store)
    assert outgoing == ['new']
    assert [call['event_id'] for call in calls] == ['old', 'new']


def test_corroborated_event_still_reaches_an_account_without_the_first_alert(tmp_path, monkeypatch):
    service, calls, current, peer = prepared_service(tmp_path, monkeypatch)
    invite = service.telegram.members.invite('telegram', 'Second account', 'viewer')
    service.telegram.members.accept(invite['code'], 'telegram', '456', client='tg')
    service.notifications.deliver_once(service.store)
    insert(service.store, peer, status='pending')
    monkeypatch.setattr('time.time', lambda: current['created']+4)
    service.notifications.deliver_once(service.store)
    assert [(call['event_id'], str(call['chat_id'])) for call in calls[1:]] == [('new', '456')]
    assert sorted(row['status'] for row in service.store.recipient_deliveries('new')) == ['grouped', 'sent']


def test_corroboration_preserves_the_silent_to_audible_upgrade(tmp_path, monkeypatch):
    service, calls, current, peer = prepared_service(tmp_path, monkeypatch)
    with service.store.db:
        service.store.db.execute("UPDATE recipient_deliveries SET audible=0 WHERE event_id='old'")
    service.notifications.deliver_once(service.store)
    insert(service.store, peer, status='pending')
    monkeypatch.setattr('time.time', lambda: current['created']+4)
    service.notifications.deliver_once(service.store)
    assert [call['event_id'] for call in calls] == ['old', 'new']
    assert calls[-1]['silent'] is False
    assert service.store.event('new')['activity_group'] == 'old'
