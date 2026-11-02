"""Persistent device sessions and one-use browser/Telegram invitations."""
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
import uuid


class Members:
    def __init__(self,settings):
        self.settings=settings
        if not settings.secret('DASHBOARD_SESSION_KEY'):
            settings.save_secrets({'DASHBOARD_SESSION_KEY':secrets.token_hex(32)})
        self.key=bytes.fromhex(settings.secret('DASHBOARD_SESSION_KEY'))
        self.key_version=hashlib.sha256(self.key).hexdigest()[:16]
        self.lock=threading.RLock()
        self.db=sqlite3.connect(settings.path/'members.db',check_same_thread=False,timeout=15)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS devices (
          id TEXT PRIMARY KEY, kind TEXT, external_id TEXT, name TEXT, role TEXT,
          created REAL, last_seen REAL, expires REAL, revoked INTEGER DEFAULT 0,
          alerts INTEGER DEFAULT 1,key_version TEXT,UNIQUE(kind,external_id));
        CREATE TABLE IF NOT EXISTS invitations (
          id TEXT PRIMARY KEY,digest TEXT UNIQUE,kind TEXT,name TEXT,role TEXT,
          expires REAL,status TEXT DEFAULT 'active',key_version TEXT);
        CREATE TABLE IF NOT EXISTS enrollment_attempts (client TEXT,created REAL);
        ''')
        self.db.commit()
        self.sync_owner()

    def digest(self,value):
        return hmac.new(self.key,('watchyard-member:'+value).encode(),hashlib.sha256).hexdigest()

    def sync_owner(self):
        owner=self.settings.secret('TELEGRAM_CHAT_ID')
        if owner is not None and self.find('telegram',str(owner)) is None:
            # Never resurrect a revoked account on service/watchdog restart.
            self.register('telegram',str(owner),'Original Telegram account','admin')

    def register(self,kind,external_id,name,role,expires=None):
        now=time.time()
        with self.lock:
            self.db.execute('INSERT OR IGNORE INTO devices (id,kind,external_id,name,role,created,last_seen,expires,key_version) VALUES (?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,kind,str(external_id),name,role,now,now,expires,self.key_version))
            self.db.commit()
            return self.find(kind,external_id)

    def find(self,kind,external_id):
        with self.lock:
            row=self.db.execute('SELECT * FROM devices WHERE kind=? AND external_id=?',(kind,str(external_id))).fetchone()
        return dict(row) if row else None

    def active(self,device):
        return bool(device and not device['revoked'] and (device['kind']!='browser' or (device['expires']>time.time() and device['key_version']==self.key_version)))

    def touch(self,device):
        if time.time()-device['last_seen']>60:
            with self.lock:
                self.db.execute('UPDATE devices SET last_seen=? WHERE id=?',(time.time(),device['id']));self.db.commit()

    def devices(self):
        self.sync_owner()
        with self.lock:
            rows=[dict(r) for r in self.db.execute('SELECT * FROM devices ORDER BY created DESC LIMIT 200')]
        return [{k:r[k] for k in ('id','kind','name','role','created','last_seen','expires','alerts')}|{'active':self.active(r)} for r in rows]

    def recipients(self,alerts_only=False):
        self.sync_owner()
        with self.lock:
            rows=[dict(r) for r in self.db.execute("SELECT * FROM devices WHERE kind='telegram' AND revoked=0 ORDER BY created")]
        return [r for r in rows if not alerts_only or r['alerts']]

    def revoke(self,device_id):
        with self.lock:
            result=self.db.execute('UPDATE devices SET revoked=1 WHERE id=?',(device_id,));self.db.commit()
            return bool(result.rowcount)

    def revoke_session(self,digest):
        device=self.find('browser',digest)
        return self.revoke(device['id']) if device else False

    def alerts(self,external_id,enabled):
        with self.lock:
            self.db.execute("UPDATE devices SET alerts=? WHERE kind='telegram' AND external_id=? AND revoked=0",(int(enabled),str(external_id)));self.db.commit()

    def invite(self,kind,name,role):
        code=secrets.token_urlsafe(18)
        key=uuid.uuid4().hex
        with self.lock:
            self.db.execute("DELETE FROM invitations WHERE expires<?",(time.time()-86400,))
            count=self.db.execute("SELECT count(*) FROM invitations WHERE status='active' AND expires>?",(time.time(),)).fetchone()[0]
            if count>=20:
                self.db.rollback()
                raise ValueError('Cancel an invitation before creating another')
            expiry=time.time()+900
            self.db.execute('INSERT INTO invitations (id,digest,kind,name,role,expires,key_version) VALUES (?,?,?,?,?,?,?)',(key,self.digest(code),kind,name,role,expiry,self.key_version));self.db.commit()
        return {'id':key,'code':code,'kind':kind,'name':name,'role':role,'expires':expiry}

    def invitations(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT id,kind,name,role,expires FROM invitations WHERE status='active' AND expires>? AND key_version=? ORDER BY expires DESC",(time.time(),self.key_version))]

    def cancel(self,key):
        with self.lock:
            result=self.db.execute("UPDATE invitations SET status='revoked' WHERE id=?",(key,));self.db.commit()
            return bool(result.rowcount)

    def accept(self,code,kind,external_id,expires=None,client=''):
        now=time.time()
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('DELETE FROM enrollment_attempts WHERE created<?',(now-300,))
                attempts=self.db.execute('SELECT count(*) FROM enrollment_attempts WHERE client=?',(client,)).fetchone()[0]
                total=self.db.execute('SELECT count(*) FROM enrollment_attempts').fetchone()[0]
                if attempts>=5 or total>=30:
                    self.db.commit();return None
                invite=self.db.execute("SELECT * FROM invitations WHERE digest=? AND kind=? AND status='active' AND expires>? AND key_version=?",(self.digest(code),kind,now,self.key_version)).fetchone()
                if not invite:
                    self.db.execute('INSERT INTO enrollment_attempts VALUES (?,?)',(client,now));self.db.commit();return None
                existing=self.db.execute('SELECT * FROM devices WHERE kind=? AND external_id=?',(kind,str(external_id))).fetchone()
                if existing and kind=='telegram' and not existing['revoked']:
                    self.db.rollback();return dict(existing)
                device_id=existing['id'] if existing else uuid.uuid4().hex
                if existing:
                    self.db.execute('UPDATE devices SET name=?,role=?,revoked=0,alerts=1,last_seen=?,expires=?,key_version=? WHERE id=?',(invite['name'],invite['role'],now,expires,self.key_version,device_id))
                else:
                    self.db.execute('INSERT INTO devices (id,kind,external_id,name,role,created,last_seen,expires,key_version) VALUES (?,?,?,?,?,?,?,?,?)',(device_id,kind,str(external_id),invite['name'],invite['role'],now,now,expires,self.key_version))
                self.db.execute("UPDATE invitations SET status='used' WHERE id=?",(invite['id'],));self.db.commit()
                return self.find(kind,external_id)
            except Exception:
                self.db.rollback();raise
