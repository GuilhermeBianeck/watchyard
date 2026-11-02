import sqlite3
import threading
import time
import uuid


class Store:
    def __init__(self,directory):
        self.directory=directory
        self.lock=threading.RLock()
        self.db=sqlite3.connect(directory/'events.db',check_same_thread=False,timeout=15)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        # The watchdog and detector may start together. Serialize migrations.
        self.db.execute('BEGIN IMMEDIATE')
        self.db.execute("""CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, created REAL, camera INTEGER, camera_name TEXT,
            label TEXT, confidence REAL, snapshot TEXT, status TEXT,
            attempts INTEGER DEFAULT 0, next_try REAL DEFAULT 0, detail TEXT DEFAULT '')""")
        columns={r[1] for r in self.db.execute('PRAGMA table_info(events)')}
        for name,definition in [('feedback',"TEXT DEFAULT 'unreviewed'"),('sent_at','REAL'),('notify_mode',"TEXT DEFAULT ''")]:
            if name not in columns:
                self.db.execute(f'ALTER TABLE events ADD COLUMN {name} {definition}')
        self.db.execute("CREATE TABLE IF NOT EXISTS recipient_deliveries (event_id TEXT,recipient TEXT,status TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0,next_try REAL DEFAULT 0,sent_at REAL,error TEXT DEFAULT '',created REAL,PRIMARY KEY(event_id,recipient))")
        self.db.execute('CREATE TABLE IF NOT EXISTS samples (created REAL, memory_mb INTEGER, online INTEGER, inference_ms REAL)')
        self.db.execute('CREATE INDEX IF NOT EXISTS samples_created ON samples(created)')
        self.db.execute('CREATE TABLE IF NOT EXISTS health_state (key TEXT PRIMARY KEY, name TEXT, healthy INTEGER, changed REAL, announced INTEGER DEFAULT 0)')
        self.db.execute("CREATE TABLE IF NOT EXISTS health_outbox (id TEXT PRIMARY KEY,key TEXT,created REAL,body TEXT,status TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0,next_try REAL DEFAULT 0)")
        self.db.commit()

    def add(self,camera,label,confidence,snapshot,status='pending',detail='',notify_mode=''):
        key=uuid.uuid4().hex
        with self.lock:
            self.db.execute('INSERT INTO events (id,created,camera,camera_name,label,confidence,snapshot,status,detail,notify_mode) VALUES (?,?,?,?,?,?,?,?,?,?)',(key,time.time(),camera['id'],camera['name'],label,confidence,snapshot,status,detail,notify_mode))
            self.db.commit()
        return key

    def recent(self,limit=50):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT * FROM events ORDER BY created DESC LIMIT ?',(limit,))]

    def pending(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM events WHERE status='pending' AND next_try<=? ORDER BY created LIMIT 4",(time.time(),))]

    def mark(self,key,status,detail='',retry_in=0):
        with self.lock:
            self.db.execute("UPDATE events SET status=?,detail=?,attempts=attempts+CASE WHEN ? IN ('pending','sent') THEN 1 ELSE 0 END,next_try=?,sent_at=CASE WHEN ?='sent' THEN ? ELSE sent_at END WHERE id=?",(status,detail,status,time.time()+retry_in,status,time.time(),key))
            self.db.commit()

    def feedback(self,key,value):
        with self.lock:
            result=self.db.execute('UPDATE events SET feedback=? WHERE id=?',(value,key))
            self.db.commit()
            return result.rowcount>0

    def sample(self,status):
        timings=[c['inference_ms'] for c in status['cameras'] if c['online'] and c['inference_ms']]
        with self.lock:
            self.db.execute('INSERT INTO samples VALUES (?,?,?,?)',(time.time(),status['memory_mb'],sum(c['online'] for c in status['cameras']),sum(timings)/len(timings) if timings else None))
            self.db.commit()

    def diagnostics(self):
        with self.lock:
            counts=dict(self.db.execute('SELECT status,count(*) FROM events GROUP BY status').fetchall())
            feedback=dict(self.db.execute('SELECT feedback,count(*) FROM events GROUP BY feedback').fetchall())
            times=[r[0] for r in self.db.execute('SELECT sent_at-created FROM events WHERE sent_at IS NOT NULL ORDER BY sent_at DESC LIMIT 1000')]
            sample=self.db.execute('SELECT count(*),max(memory_mb),avg(inference_ms) FROM samples WHERE created>?',(time.time()-86400,)).fetchone()
            health=[dict(r) for r in self.db.execute('SELECT * FROM health_outbox ORDER BY created DESC LIMIT 15')]
        return {'delivery':counts,'reviews':feedback,'mean_delivery_seconds':round(sum(times)/len(times),1) if times else None,'delivery_sample_count':len(times),'samples_24h':sample[0],'peak_memory_mb':sample[1],'mean_inference_ms':round(sample[2],1) if sample[2] else None,'health_events':health}

    def observe_health(self,key,name,healthy,now=None,debounce=45):
        now=time.time() if now is None else now
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.db.execute('SELECT * FROM health_state WHERE key=?',(key,)).fetchone()
            if row is None:
                self.db.execute('INSERT INTO health_state (key,name,healthy,changed) VALUES (?,?,?,?)',(key,name,int(healthy),now))
            elif bool(row['healthy'])!=healthy:
                if healthy and row['announced']:
                    # Supersede a stale offline notice rather than deliver it after recovery.
                    self.db.execute("UPDATE health_outbox SET status='superseded' WHERE key=? AND status='pending'",(key,))
                    self._queue_health(key,f'{name} recovered after {int(now-row["changed"])} seconds.',now)
                self.db.execute('UPDATE health_state SET healthy=?,changed=?,announced=0,name=? WHERE key=?',(int(healthy),now,name,key))
            elif not healthy and not row['announced'] and now-row['changed']>=debounce:
                self._queue_health(key,f'{name} is unavailable. Watchyard will keep trying to reconnect.',now)
                self.db.execute('UPDATE health_state SET announced=1 WHERE key=?',(key,))
            self.db.commit()

    def _queue_health(self,key,body,now):
        self.db.execute('INSERT INTO health_outbox (id,key,created,body) VALUES (?,?,?,?)',(uuid.uuid4().hex,key,now,body))

    def pending_health(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM health_outbox WHERE status='pending' AND next_try<=? ORDER BY created LIMIT 4",(time.time(),))]

    def mark_health(self,key,sent,retry_in=15):
        with self.lock:
            self.db.execute('UPDATE health_outbox SET status=?,attempts=attempts+1,next_try=? WHERE id=?',('sent' if sent else 'pending',time.time()+retry_in,key))
            self.db.commit()

    def ensure_recipients(self,event_id,recipients):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            count=self.db.execute('SELECT count(*) FROM recipient_deliveries WHERE event_id=?',(event_id,)).fetchone()[0]
            if not count:
                self.db.executemany('INSERT OR IGNORE INTO recipient_deliveries (event_id,recipient,created) VALUES (?,?,?)',[(event_id,r['id'],time.time()) for r in recipients])
            self.db.commit()

    def recipient_deliveries(self,event_id):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT * FROM recipient_deliveries WHERE event_id=?',(event_id,))]

    def recipient_result(self,event_id,recipient,status,error='',retry_in=0):
        with self.lock:
            self.db.execute("UPDATE recipient_deliveries SET status=?,attempts=attempts+CASE WHEN ? IN ('pending','sent') THEN 1 ELSE 0 END,next_try=?,sent_at=CASE WHEN ?='sent' THEN ? ELSE sent_at END,error=? WHERE event_id=? AND recipient=?",(status,status,time.time()+retry_in,status,time.time(),error,event_id,recipient))
            self.db.commit()

    def cleanup(self,days):
        cutoff=time.time()-days*86400
        with self.lock:
            rows=self.db.execute('SELECT snapshot FROM events WHERE created<?',(cutoff,)).fetchall()
            for row in rows:
                (self.directory/'events'/row['snapshot']).unlink(missing_ok=True)
            self.db.execute('DELETE FROM events WHERE created<?',(cutoff,))
            self.db.execute('DELETE FROM samples WHERE created<?',(cutoff,))
            self.db.execute('DELETE FROM recipient_deliveries WHERE created<?',(cutoff,))
            self.db.execute('DELETE FROM health_outbox WHERE created<?',(cutoff,))
            self.db.commit()
