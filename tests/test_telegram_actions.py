import json
import time

from fastapi.testclient import TestClient

from watchyard.app import create_app
from watchyard.config import Settings
from watchyard.service import Service
from watchyard.telegram import TelegramAPIError


def configured_service(tmp_path):
    settings = Settings(tmp_path)
    settings.save_secrets({'TELEGRAM_CHAT_ID': 123})
    return Service(settings)


def callback(data, message=None, user=123):
    return {'callback_query': {'id': 'press', 'from': {'id': user}, 'data': data,
                               'message': {'chat': {'id': 123, 'type': 'private'}, **(message or {})}}}


def test_review_acks_in_place_and_unauthorized_callbacks_do_not_act(tmp_path):
    service = configured_service(tmp_path)
    bot = service.telegram
    event = service.store.add({'id': 1, 'name': 'Gate'}, 'person', .9, 'test.jpg')
    calls = []
    bot.call = lambda method, data=None, **kwargs: calls.append((method, data))
    bot.handle(callback('review:useful:' + event, user=999))
    assert calls[-1][0] == 'answerCallbackQuery'
    assert service.store.event(event)['feedback'] == 'unreviewed'
    bot.handle(callback('review:useful:' + event))
    assert service.store.event(event)['feedback'] == 'useful'
    assert calls[-1] == ('answerCallbackQuery', {'callback_query_id': 'press', 'text': 'Review saved.'})
    assert all(method == 'answerCallbackQuery' for method, _ in calls)


def test_pause_button_updates_controls_without_sending_a_message(tmp_path):
    bot = configured_service(tmp_path).telegram
    calls = []
    bot.call = lambda method, data=None, **kwargs: calls.append((method, data))
    bot.handle(callback('notifications:off', {'message_id': 7, 'text': 'Your alerts are on.'}))
    assert not bot.recipient_devices()
    assert [method for method, _ in calls] == ['answerCallbackQuery', 'editMessageText']
    rows = json.loads(calls[-1][1]['reply_markup'])['inline_keyboard']
    assert rows[0][0]['callback_data'] == 'notifications:on'


def test_vehicle_group_alert_links_to_its_replays_and_snapshots_have_no_controls(tmp_path):
    service = configured_service(tmp_path)
    bot = service.telegram
    event = service.store.add({'id': 1, 'name': 'Gate'}, 'car', .9, 'test.jpg')
    service.store.assign_activity_group(event, event, '')
    calls = []
    bot.call = lambda method, data=None, **kwargs: calls.append(data)
    bot.photo(b'image', 'Vehicle', event_id=event, chat_id=123)
    rows = json.loads(calls[-1]['reply_markup'])['inline_keyboard']
    assert rows[0][0]['url'].endswith('#event=' + event)
    assert rows[0][1]['url'].endswith('#group=' + event)
    bot.photo(b'image', 'Snapshot', chat_id=123)
    assert 'reply_markup' not in calls[-1]
    client = TestClient(create_app(service, run_service=False))
    response = client.get('/api/activity/preview', params={'group': event})
    assert response.json()[0]['id'] == event


def test_telegram_retry_respects_server_delay(tmp_path):
    service = configured_service(tmp_path)
    (tmp_path/'events'/'test.jpg').write_bytes(b'image')
    event = service.store.add({'id': 1, 'name': 'Gate'}, 'person', .9, 'test.jpg')

    def limited(*args, **kwargs):
        raise TelegramAPIError(429, 45)

    service.telegram.photo = limited
    now = time.time()
    service.notifications.deliver_once(service.store)
    assert service.store.recipient_deliveries(event)[0]['next_try'] >= now + 45
