import sqlite3

from watchyard.config import Settings
from watchyard.health import OUTAGE, RECOVERY
from watchyard.notifications import Notifications
from watchyard.store import Store


class Bot:
    def __init__(self):
        self.destinations = ('owner', 'guest')
        self.messages = []
        self.offline = set()

    def recipient_devices(self):
        return [{'id': target, 'external_id': target} for target in self.destinations]

    def text(self, message, *, chat_id, **options):
        if chat_id in self.offline:
            raise RuntimeError('offline')
        self.messages.append((chat_id, message, options['disable_notification']))


class HealthRun:
    def __init__(self, path, monkeypatch):
        self.now = 1000
        monkeypatch.setattr('watchyard.store.time.time', lambda: self.now)
        self.store = Store(path)
        self.bot = Bot()
        self.notifications = Notifications(Settings(path), self.bot)

    def step(self, offset, down=()):
        self.now = 1000 + offset
        self.store.observe_cameras((i, f'View {i}', i not in down) for i in (1, 2, 3, 4))
        self.notifications.flush_health(self.store)


def test_staggered_four_camera_outage_and_recovery_send_one_each_per_account(tmp_path, monkeypatch):
    run = HealthRun(tmp_path, monkeypatch)
    run.step(0)
    run.step(15, down=(1, 2, 3))
    run.step(30, down=(1, 2, 3, 4))
    run.step(60, down=(1, 2, 3, 4))
    run.step(75, down=(1, 2, 3, 4))
    assert not run.bot.messages
    run.store = Store(tmp_path)
    run.step(90, down=(1, 2, 3, 4))
    assert len(run.bot.messages) == 2
    for _, message, silent in run.bot.messages:
        assert message.startswith('4 cameras are unavailable') and silent == 'true'
        assert all(f'View {i}' in message for i in (1, 2, 3, 4))

    run.step(150, down=(1, 2, 3))
    run.step(166)
    run.step(181)
    run.step(196)
    run.step(211)
    run.step(241)
    assert len(run.bot.messages) == 4
    assert all(message.startswith('4 cameras recovered') for _, message, _ in run.bot.messages[2:])
    assert {e['key']: e['status'] for e in run.store.diagnostics()['health_events']} == {OUTAGE: 'sent', RECOVERY: 'sent'}


def test_recovery_only_goes_to_recipients_that_received_the_outage(tmp_path, monkeypatch):
    run = HealthRun(tmp_path, monkeypatch)
    run.bot.offline.add('guest')
    run.step(0, down=(1, 2))
    run.step(45, down=(1, 2))
    run.step(75, down=(1, 2))
    assert [target for target, _, _ in run.bot.messages] == ['owner']
    run.step(90)
    run.step(120)
    run.bot.offline.clear()
    run.step(150)
    assert len(run.bot.messages) == 2
    assert run.bot.messages[-1][:2] == ('owner', '2 cameras recovered.\n• View 1 (90s offline)\n• View 2 (90s offline)')


def test_unseen_outage_and_brief_flap_do_not_create_orphan_recovery(tmp_path, monkeypatch):
    run = HealthRun(tmp_path, monkeypatch)
    run.step(0, down=(1, 2))
    run.step(45, down=(1, 2))
    run.step(60)
    run.step(75)
    assert not run.bot.messages
    run.step(90)
    run.step(120)
    assert not run.bot.messages
    assert all(e['status'] == 'superseded' for e in run.store.diagnostics()['health_events'])

    run.step(150, down=(1,))
    run.step(195, down=(1,))
    run.step(225, down=(1,))
    run.step(240)
    run.step(255, down=(1,))
    run.step(285, down=(1,))
    run.step(315, down=(1,))
    assert len(run.bot.messages) == 2
    assert all('unavailable' in message for _, message, _ in run.bot.messages)


def test_retries_report_only_still_active_cameras_and_remember_coverage(tmp_path, monkeypatch):
    run = HealthRun(tmp_path, monkeypatch)
    run.bot.offline.add('guest')
    run.step(0, down=(1, 2))
    run.step(45, down=(1, 2))
    run.step(75, down=(1, 2))
    run.step(90, down=(2,))
    run.bot.offline.clear()
    run.step(120, down=(2,))
    run.step(150, down=(2,))
    run.step(180)
    run.step(210)
    run.step(240)
    owner = [message for target, message, _ in run.bot.messages if target == 'owner']
    guest = [message for target, message, _ in run.bot.messages if target == 'guest']
    assert [message.split()[0] for message in owner] == ['2', 'View', 'View']
    assert len(guest) == 2 and all('View 2' in message for message in guest)
    assert all('View 1' not in message for message in guest)


def test_long_outage_without_any_delivery_gets_one_summary_when_network_returns(tmp_path, monkeypatch):
    run = HealthRun(tmp_path, monkeypatch)
    run.bot.offline.update(run.bot.destinations)
    run.step(0, down=(1, 2, 3, 4))
    run.step(45, down=(1, 2, 3, 4))
    run.step(75, down=(1, 2, 3, 4))
    run.step(3040, down=(2, 3, 4))
    run.step(3055)
    run.step(3070)
    run.step(3085)
    run.bot.offline.clear()
    run.step(3100)
    assert len(run.bot.messages) == 2
    assert all(message.startswith('4 cameras recovered') for _, message, _ in run.bot.messages)


def test_a_later_unrelated_outage_still_alerts(tmp_path, monkeypatch):
    run = HealthRun(tmp_path, monkeypatch)
    run.step(0, down=(1,))
    run.step(45, down=(1,))
    run.step(75, down=(1,))
    run.step(120, down=(1, 2))
    run.step(165, down=(1, 2))
    run.step(195, down=(1, 2))
    owner = [message for target, message, _ in run.bot.messages if target == 'owner']
    assert len(owner) == 2
    assert owner[0].startswith('View 1 is unavailable')
    assert owner[1].startswith('View 2 is unavailable')


def test_upgrade_retires_pending_individual_camera_notices_only(tmp_path):
    with sqlite3.connect(tmp_path / 'events.db') as db:
        db.executescript("""
            CREATE TABLE health_outbox (id TEXT PRIMARY KEY,key TEXT,created REAL,body TEXT,
                status TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0,next_try REAL DEFAULT 0);
            INSERT INTO health_outbox (id,key,created,body,status) VALUES
                ('camera-sent','camera-1',1,'Earlier delivery','sent'),
                ('camera-pending','camera-2',2,'Old individual delivery','pending'),
                ('watchdog','service',3,'Service unavailable','pending');
            """)
    store = Store(tmp_path)
    assert {event['id']: event['status'] for event in store.diagnostics()['health_events']} == {
        'camera-sent': 'sent', 'camera-pending': 'superseded', 'watchdog': 'pending',
    }
    assert [event['id'] for event in Store(tmp_path).pending_health()] == ['watchdog']
