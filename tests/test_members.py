import time
from fastapi.testclient import TestClient
from watchyard.config import Settings
from watchyard.service import Service
from watchyard.app import create_app
from watchyard.access import Access
from watchyard.members import Members

H={'X-Watchyard-Client':'dashboard'}


def setup(tmp_path):
    service=Service(Settings(tmp_path));app=create_app(service,run_service=False)
    return service,app,TestClient(app)


def test_invites_are_one_time_kind_bound_and_expire(tmp_path):
    m=Members(Settings(tmp_path));invite=m.invite('browser','Phone','viewer')
    assert m.accept(invite['code'],'telegram','999',client='tg') is None
    one=m.accept(invite['code'],'browser','token1',time.time()+600,client='b1')
    assert one['role']=='viewer'
    assert m.accept(invite['code'],'browser','token2',time.time()+600,client='b2') is None
    expired=m.invite('browser','Old','admin')
    m.db.execute('UPDATE invitations SET expires=0 WHERE id=?',(expired['id'],));m.db.commit()
    assert m.accept(expired['code'],'browser','token3',time.time()+600,client='b3') is None
    cancelled=m.invite('telegram','Cancelled','viewer');m.cancel(cancelled['id'])
    assert m.accept(cancelled['code'],'telegram','2',client='tg2') is None


def test_membership_persists_and_revoked_owner_stays_revoked(tmp_path):
    settings=Settings(tmp_path);settings.save_secrets({'TELEGRAM_CHAT_ID':123})
    m=Members(settings);owner=m.recipients()[0];m.revoke(owner['id'])
    assert Members(Settings(tmp_path)).recipients()==[]
    assert m.invite('browser','New phone','viewer')['code']


def test_legacy_signed_session_migrates_and_revocation_is_immediate(tmp_path):
    service,app,owner=setup(tmp_path)
    access=Access(service.settings)
    value=str(int(time.time()+600))+'.legacy_nonce';token=value+'.'+access.digest(value)
    # Use a real LAN client and host; configure the app's allowlist deterministically.
    from unittest.mock import patch
    import ipaddress
    with patch('watchyard.app.lan_address',return_value='192.168.1.144'),patch('watchyard.app.lan_network',return_value=ipaddress.ip_network('192.168.1.0/24')):
        app=create_app(service,run_service=False)
    mobile=TestClient(app,base_url='http://192.168.1.144:8765',client=('192.168.1.200',50000));mobile.cookies.set(Access.cookie,token)
    assert mobile.get('/api/session').json()['device']['role']=='admin'
    current=mobile.get('/api/session').json()['device']['id']
    assert TestClient(app).post('/api/devices/'+current+'/revoke',json={},headers=H).status_code==200
    assert mobile.get('/api/status').status_code==401
    assert not mobile.get('/api/session').json()['authenticated']


def test_browser_viewer_cannot_manage_or_invite(tmp_path,monkeypatch):
    import ipaddress
    monkeypatch.setattr('watchyard.app.lan_address',lambda:'192.168.1.144')
    monkeypatch.setattr('watchyard.app.lan_network',lambda x:ipaddress.ip_network('192.168.1.0/24'))
    service,app,owner=setup(tmp_path)
    invitation=owner.post('/api/invitations',headers=H,json={'kind':'browser','name':'Living room tablet'}).json()
    viewer=TestClient(app,base_url='http://192.168.1.144:8765',client=('192.168.1.200',50000))
    assert viewer.post('/api/login',headers=H,json={'code':invitation['code'],'name':'Tablet'}).status_code==200
    assert viewer.get('/api/session').json()['device']['role']=='viewer'
    assert viewer.get('/api/status').status_code==200
    assert viewer.get('/api/devices').status_code==403
    assert viewer.post('/api/controls',headers=H,json={'enabled':False}).status_code==403
    assert viewer.post('/api/invitations',headers=H,json={'kind':'telegram','name':'Bad','role':'admin'}).status_code==403
    token=viewer.cookies.get(Access.cookie)
    assert viewer.post('/api/logout',headers=H,json={}).status_code==200
    assert viewer.get('/api/status').status_code==401
    viewer.cookies.set(Access.cookie,token)
    assert viewer.get('/api/status').status_code==401


def test_invitation_requires_a_nonblank_name(tmp_path):
    _,_,owner=setup(tmp_path)
    assert owner.post('/api/invitations',headers=H,json={'kind':'browser','name':'   '}).status_code==422


def test_expired_telegram_invitation_explains_how_to_retry(tmp_path):
    service,_,_=setup(tmp_path)
    invite=service.telegram.members.invite('telegram','Other account','viewer')
    service.telegram.members.cancel(invite['id'])
    calls=[];service.telegram.call=lambda method,data=None,**kw:calls.append((method,data))
    service.telegram.handle({'message':{'text':'/start '+invite['code'],'chat':{'id':456,'type':'private'},'from':{'id':456}}})
    assert len(calls)==1 and calls[0][0]=='sendMessage'
    assert calls[0][1]['chat_id']==456 and 'new Telegram account invitation' in calls[0][1]['text']
    assert not service.telegram.paired()


def test_telegram_invites_authorize_only_private_matching_identity(tmp_path):
    service,_,_=setup(tmp_path);m=service.telegram.members
    invite=m.invite('telegram','Another account','viewer')
    sent=[];service.telegram.text=lambda *a,**k:sent.append(k.get('chat_id'))
    def update(chat,user,kind='private'):
        return {'message':{'text':'/start '+invite['code'],'chat':{'id':chat,'type':kind},'from':{'id':user}}}
    service.telegram.handle(update(456,999))
    service.telegram.handle(update(456,456,'group'))
    assert not service.telegram.paired()
    service.telegram.handle(update(456,456))
    assert service.telegram.allowed({'id':456,'type':'private'},{'id':456})
    assert sent==[456]
    service.telegram.handle({'message':{'text':'/mute 60','chat':{'id':456,'type':'private'},'from':{'id':456}}})
    assert service.settings.snapshot()['muted_until']==0
    member=m.find('telegram','456');m.revoke(member['id'])
    assert not service.telegram.allowed({'id':456,'type':'private'},{'id':456})


def test_recipient_failure_does_not_resend_successes(tmp_path):
    service,_,_=setup(tmp_path);service.settings.save_secrets({'TELEGRAM_CHAT_ID':123})
    m=service.telegram.members;m.sync_owner()
    invite=m.invite('telegram','Second account','viewer');m.accept(invite['code'],'telegram','456',client='tg')
    (tmp_path/'events'/'test.jpg').write_bytes(b'image')
    key=service.store.add({'id':1,'name':'Gate'},'person',.8,'test.jpg')
    calls=[]
    def photo(*a,**kwargs):
        calls.append(str(kwargs['chat_id']))
        if str(kwargs['chat_id'])=='456':raise RuntimeError('unavailable')
    service.telegram.photo=photo;service.telegram.deliver_once()
    assert sorted(calls)==['123','456']
    with service.store.lock:
        service.store.db.execute('UPDATE events SET next_try=0 WHERE id=?',(key,))
        service.store.db.execute('UPDATE recipient_deliveries SET next_try=0 WHERE event_id=?',(key,));service.store.db.commit()
    service.telegram.photo=lambda *a,**kw:calls.append(str(kw['chat_id']))
    service.telegram.deliver_once()
    assert calls.count('123')==1 and calls.count('456')==2
    assert service.store.recent()[0]['status']=='sent'


def test_telegram_status_reply_is_not_broadcast(tmp_path):
    service,_,_=setup(tmp_path);service.settings.save_secrets({'TELEGRAM_CHAT_ID':123})
    m=service.telegram.members;m.sync_owner();invite=m.invite('telegram','Second','viewer');m.accept(invite['code'],'telegram','456',client='tg')
    calls=[];service.telegram.call=lambda method,data=None,**kw:calls.append((method,data))
    service.telegram.handle({'message':{'text':'/status','chat':{'id':456,'type':'private'},'from':{'id':456}}})
    assert len(calls)==1 and str(calls[0][1]['chat_id'])=='456'


def test_existing_telegram_owner_cannot_be_downgraded_by_using_viewer_invite(tmp_path):
    settings=Settings(tmp_path);settings.save_secrets({'TELEGRAM_CHAT_ID':123})
    m=Members(settings);invite=m.invite('telegram','Other person','viewer')
    result=m.accept(invite['code'],'telegram','123',client='telegram:123')
    assert result['role']=='admin'
    assert len(m.invitations())==1
    result=m.accept(invite['code'],'telegram','456',client='telegram:456')
    assert result['role']=='viewer'


def test_registry_output_never_exposes_session_tokens_or_invite_codes(tmp_path):
    m=Members(Settings(tmp_path));invite=m.invite('browser','Tablet','viewer')
    m.accept(invite['code'],'browser','sensitive-session-digest',time.time()+600,client='b')
    result=str(m.devices())+str(m.invitations())
    assert invite['code'] not in result
    assert 'sensitive-session-digest' not in result


def test_revoked_recipient_is_not_retried(tmp_path):
    service,_,_=setup(tmp_path);service.settings.save_secrets({'TELEGRAM_CHAT_ID':123})
    m=service.telegram.members;m.sync_owner();invite=m.invite('telegram','Other','viewer')
    second=m.accept(invite['code'],'telegram','456',client='tg')
    (tmp_path/'events'/'test.jpg').write_bytes(b'image')
    key=service.store.add({'id':1,'name':'Gate'},'person',.8,'test.jpg')
    def photo(*a,**kw):
        if str(kw['chat_id'])=='456':raise RuntimeError('offline')
    service.telegram.photo=photo;service.telegram.deliver_once();m.revoke(second['id'])
    service.store.db.execute('UPDATE events SET next_try=0 WHERE id=?',(key,));service.store.db.commit()
    calls=[];service.telegram.photo=lambda *a,**k:calls.append(k)
    service.telegram.deliver_once()
    assert not calls
    assert service.store.recent()[0]['status']=='sent'


def test_telegram_pause_is_per_account(tmp_path):
    service,_,_=setup(tmp_path);service.settings.save_secrets({'TELEGRAM_CHAT_ID':123})
    m=service.telegram.members;m.sync_owner();invite=m.invite('telegram','Other','viewer');m.accept(invite['code'],'telegram','456',client='tg')
    service.telegram.text=lambda *a,**k:None
    service.telegram.handle({'message':{'text':'/notifications off','chat':{'id':456,'type':'private'},'from':{'id':456}}})
    assert [r['external_id'] for r in service.telegram.recipient_devices()]==['123']
    assert service.settings.snapshot()['muted_until']==0
    assert service.telegram.allowed({'id':456,'type':'private'},{'id':456})


def test_concurrent_invitation_use_registers_only_one_device(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    settings=Settings(tmp_path);first=Members(settings);second=Members(settings)
    invite=first.invite('browser','One phone','viewer')
    def accept(pair):
        registry,token=pair
        return registry.accept(invite['code'],'browser',token,time.time()+600,client=token)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(accept,[(first,'one'),(second,'two')]))
    assert sum(r is not None for r in results)==1


def test_health_delivery_is_tracked_per_recipient(tmp_path):
    from watchyard.watchdog import flush_health
    service,_,_=setup(tmp_path);service.settings.save_secrets({'TELEGRAM_CHAT_ID':123})
    m=service.telegram.members;m.sync_owner();invite=m.invite('telegram','Other','viewer');m.accept(invite['code'],'telegram','456',client='tg')
    s=service.store;s.observe_health('cam','Gate',False,now=0);s.observe_health('cam','Gate',False,now=60)
    calls=[]
    def text(*a,**kw):
        calls.append(str(kw['chat_id']))
        if str(kw['chat_id'])=='456':raise RuntimeError('offline')
    service.telegram.text=text;flush_health(s,service.telegram)
    s.db.execute('UPDATE health_outbox SET next_try=0');s.db.execute('UPDATE recipient_deliveries SET next_try=0');s.db.commit()
    service.telegram.text=lambda *a,**kw:calls.append(str(kw['chat_id']))
    flush_health(s,service.telegram)
    assert calls.count('123')==1 and calls.count('456')==2
    assert s.diagnostics()['health_events'][0]['status']=='sent'
