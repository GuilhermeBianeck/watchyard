import json
import sqlite3
import threading
import time
import uuid

from .health import (
    COALESCE_SECONDS, OUTAGE, OUTAGE_SECONDS, RECOVERY, RECOVERY_SECONDS, REPORT_UNDELIVERED_AFTER, camera_message,
)


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
        for name,definition in [('feedback',"TEXT DEFAULT 'unreviewed'"),('sent_at','REAL'),('notify_mode',"TEXT DEFAULT ''"),('first_seen','REAL'),('last_seen','REAL'),('plate','TEXT'),('correlation_hint','TEXT'),('activity_group','TEXT'),('activity_reason','TEXT'),('last_x','REAL'),('last_y','REAL')]:
            if name not in columns:
                self.db.execute(f'ALTER TABLE events ADD COLUMN {name} {definition}')
        self.db.execute("CREATE TABLE IF NOT EXISTS recipient_deliveries (event_id TEXT,recipient TEXT,status TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0,next_try REAL DEFAULT 0,sent_at REAL,error TEXT DEFAULT '',created REAL,PRIMARY KEY(event_id,recipient))")
        self.db.execute('CREATE TABLE IF NOT EXISTS samples (created REAL, memory_mb INTEGER, online INTEGER, inference_ms REAL)')
        self.db.execute('CREATE INDEX IF NOT EXISTS samples_created ON samples(created)')
        self.db.execute('CREATE TABLE IF NOT EXISTS health_state (key TEXT PRIMARY KEY, name TEXT, healthy INTEGER, changed REAL, announced INTEGER DEFAULT 0)')
        self.db.execute("CREATE TABLE IF NOT EXISTS health_outbox (id TEXT PRIMARY KEY,key TEXT,created REAL,body TEXT,status TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0,next_try REAL DEFAULT 0)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS incident_assessments (
            event_id TEXT PRIMARY KEY, assessed_at REAL NOT NULL, presence TEXT NOT NULL,
            outcome TEXT NOT NULL, reason TEXT NOT NULL, zone TEXT NOT NULL,
            observations INTEGER NOT NULL, dwell_seconds REAL NOT NULL)""")
        self.db.execute('CREATE INDEX IF NOT EXISTS incident_assessed_at ON incident_assessments(assessed_at DESC)')
        for table, additions in {
            'events': [('recent_colors', 'TEXT'), ('last_motion', 'REAL')],
            'health_state': [('outage_id', 'TEXT'), ('outage_since', 'REAL')],
            'health_outbox': [('camera_changes', 'TEXT')],
            'recipient_deliveries': [('coverage', 'TEXT')],
        }.items():
            existing = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
            for column, definition in additions:
                if column not in existing:
                    self.db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
                    if column == 'camera_changes':
                        self.db.execute("""
                            UPDATE health_outbox SET status='superseded'
                            WHERE status='pending' AND key GLOB 'camera-[0-9]*'
                            """)
        self.db.commit()

    def add(self,camera,label,confidence,snapshot,status='pending',detail='',notify_mode='',*,first_seen=None,last_seen=None,correlation_hint=None,last_motion=None):
        key=uuid.uuid4().hex
        with self.lock:
            self.db.execute("""
                INSERT INTO events (id,created,camera,camera_name,label,confidence,snapshot,status,detail,notify_mode,
                first_seen,last_seen,correlation_hint,last_motion) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (key,time.time(),camera['id'],camera['name'],label,confidence,snapshot,status,detail,notify_mode,
                      first_seen,last_seen,correlation_hint,last_motion))
            self.db.commit()
        return key

    def extend_observations(self, event_ids, seen, *, footprints=None, colors=None, moving=()):
        if not event_ids:
            return
        footprints = footprints or {}
        colors = colors or {}
        with self.lock:
            self.db.executemany(
                'UPDATE events SET last_seen=?, last_x=COALESCE(?,last_x), last_y=COALESCE(?,last_y), '
                'recent_colors=COALESCE(?,recent_colors), last_motion=COALESCE(?,last_motion) '
                'WHERE id=? AND last_seen<?',
                [(seen, *footprints.get(key, (None, None)), colors.get(key), seen if key in moving else None, key, seen)
                 for key in event_ids],
            )
            self.db.commit()

    def save_incident_assessment(self, event_id, assessed_at, presence, outcome, reason, zone, observations, dwell_seconds):
        # Keep the evidence that qualified the event for urgent review, even after it ends.
        with self.lock, self.db:
            self.db.execute("""
                INSERT INTO incident_assessments
                SELECT id, ?, ?, ?, ?, ?, ?, ? FROM events WHERE id=?
                ON CONFLICT(event_id) DO UPDATE SET assessed_at=excluded.assessed_at,
                  presence=excluded.presence, outcome=excluded.outcome, reason=excluded.reason,
                  zone=excluded.zone, observations=excluded.observations, dwell_seconds=excluded.dwell_seconds
                WHERE incident_assessments.outcome!='urgent'
                  AND incident_assessments.assessed_at <= excluded.assessed_at
                """, (assessed_at, presence, outcome, reason, zone, observations, dwell_seconds, event_id))

    def incident_assessments(self):
        with self.lock:
            return [dict(row) for row in self.db.execute("""
                SELECT a.*, e.camera_name, e.created, e.feedback, e.activity_group
                FROM incident_assessments a JOIN events e ON e.id=a.event_id
                ORDER BY a.assessed_at DESC LIMIT 30
                """)]

    def save_plate(self, event_id, plate):
        with self.lock:
            self.db.execute("UPDATE events SET plate=? WHERE id=? AND label='car' AND plate IS NULL",
                            (plate, event_id))
            self.db.commit()

    def correlation_events(self, *, before=None):
        now = time.time()
        with self.lock:
            return [dict(row) for row in self.db.execute(
                "SELECT id,created,camera,camera_name,label,first_seen,last_seen,feedback,plate,correlation_hint,"
                "activity_group,activity_reason,last_x,last_y,recent_colors,last_motion FROM events WHERE created>=? AND created<=? "
                "AND label IN ('person','car') ORDER BY created DESC,id DESC LIMIT 480",
                (now-7*86400, now if before is None else before))]

    def assign_activity_group(self, event_id, group_id, reason):
        with self.lock:
            self.db.execute(
                'UPDATE events SET activity_group=?,activity_reason=? WHERE id=? AND activity_group IS NULL',
                (group_id, reason, event_id))
            self.db.commit()
            row = self.db.execute('SELECT activity_group FROM events WHERE id=?', (event_id,)).fetchone()
            return row[0] if row else None

    def activity_delivered(self, group_id, event_id, recipient):
        with self.lock:
            return self.db.execute(
                "SELECT 1 FROM events e JOIN recipient_deliveries d ON d.event_id=e.id "
                "WHERE (e.activity_group=? OR e.id=?) AND e.id!=? AND e.feedback!='false_alarm' AND d.recipient=? AND d.status='sent' LIMIT 1",
                (group_id, group_id, event_id, recipient),
            ).fetchone() is not None

    def recent(self,limit=50):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT * FROM events ORDER BY created DESC LIMIT ?',(limit,))]

    def event(self,key):
        with self.lock:
            row=self.db.execute('SELECT * FROM events WHERE id=?',(key,)).fetchone()
        return dict(row) if row else None

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
            suppressed = self.db.execute(
                "SELECT count(*) FROM recipient_deliveries WHERE status='grouped' AND created>=?",
                (time.time()-86400,),
            ).fetchone()[0]
            health=[dict(r) for r in self.db.execute('SELECT * FROM health_outbox ORDER BY created DESC LIMIT 15')]
        return {'delivery':counts,'telegram_suppressed_24h':suppressed,'reviews':feedback,'mean_delivery_seconds':round(sum(times)/len(times),1) if times else None,'delivery_sample_count':len(times),'samples_24h':sample[0],'peak_memory_mb':sample[1],'mean_inference_ms':round(sample[2],1) if sample[2] else None,'health_events':health}

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

    def observe_cameras(self, observations, now=None):
        now = time.time() if now is None else now
        outages, recoveries = {}, {}
        with self.lock, self.db:
            self.db.execute('BEGIN IMMEDIATE')
            for camera_id, name, healthy in observations:
                key = 'camera-' + str(camera_id)
                row = self.db.execute('SELECT * FROM health_state WHERE key=?', (key,)).fetchone()
                if row is None:
                    self.db.execute('INSERT INTO health_state (key,name,healthy,changed) VALUES (?,?,?,?)',
                                    (key, name, healthy, now))
                elif healthy != row['healthy']:
                    self.db.execute('UPDATE health_state SET name=?,healthy=?,changed=? WHERE key=?',
                                    (name, healthy, now, key))
                elif not healthy and row['outage_id'] is None and now - row['changed'] >= OUTAGE_SECONDS:
                    outages[key] = {'name': name, 'since': row['changed']}
                elif healthy and row['outage_id'] and now - row['changed'] >= RECOVERY_SECONDS:
                    recoveries[key] = {
                        'name': name, 'outage': row['outage_id'], 'recovered_at': row['changed'],
                        'duration': int(row['changed'] - row['outage_since']),
                    }
            if outages:
                batch = self._queue_camera_health(OUTAGE, outages, now)
                self.db.executemany('UPDATE health_state SET outage_id=?,outage_since=? WHERE key=?',
                                    [(batch, item['since'], key) for key, item in outages.items()])
            if recoveries:
                self._queue_camera_health(RECOVERY, recoveries, now)
                self.db.executemany('UPDATE health_state SET outage_id=NULL,outage_since=NULL WHERE key=?',
                                    [(key,) for key in recoveries])

    def _queue_camera_health(self, kind, changes, now):
        batch = self.db.execute("""
            SELECT id,camera_changes FROM health_outbox
            WHERE key=? AND status='pending' AND created>? AND camera_changes IS NOT NULL
            ORDER BY created DESC LIMIT 1
            """, (kind, now - COALESCE_SECONDS)).fetchone()
        if batch:
            combined = json.loads(batch['camera_changes']) | changes
            self.db.execute('UPDATE health_outbox SET body=?,camera_changes=? WHERE id=?',
                            (camera_message(kind, combined), json.dumps(combined), batch['id']))
            return batch['id']
        key = uuid.uuid4().hex
        self.db.execute("""
            INSERT INTO health_outbox (id,key,created,body,next_try,camera_changes) VALUES (?,?,?,?,?,?)
            """, (key, kind, now, camera_message(kind, changes), now + COALESCE_SECONDS, json.dumps(changes)))
        return key

    def camera_health_changes(self, event, recipient):
        changes = json.loads(event['camera_changes'])
        with self.lock:
            active = {row['key']: row for row in self.db.execute(
                "SELECT * FROM health_state WHERE key LIKE 'camera-%'")}
            if event['key'] == OUTAGE:
                current = {key: item for key, item in changes.items()
                           if key in active and active[key]['outage_id'] == event['id']}
                if current and all(active[key]['healthy'] for key in current):
                    # Wait for recovery to settle before reporting an outage
                    # that may have ended during the batching window.
                    return None
                return current
            eligible = {}
            for key, item in changes.items():
                row = active.get(key)
                if not row or not row['healthy'] or row['changed'] != item['recovered_at']:
                    continue
                receipt = self.db.execute("""
                    SELECT coverage,attempts FROM recipient_deliveries WHERE event_id=? AND recipient=?
                    """, ('health:' + item['outage'], recipient)).fetchone()
                if receipt and (key in json.loads(receipt['coverage'] or '[]')
                                or (receipt['attempts'] and item['duration'] >= REPORT_UNDELIVERED_AFTER)):
                    eligible[key] = item
            return eligible

    def _queue_health(self,key,body,now):
        self.db.execute('INSERT INTO health_outbox (id,key,created,body) VALUES (?,?,?,?)',(uuid.uuid4().hex,key,now,body))

    def pending_health(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM health_outbox WHERE status='pending' AND next_try<=? ORDER BY created LIMIT 4",(time.time(),))]

    def mark_health(self,key,status,retry_in=15):
        with self.lock:
            self.db.execute("UPDATE health_outbox SET status=?,attempts=attempts+1,next_try=? WHERE id=? AND status='pending'",
                            (status,time.time()+retry_in,key))
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

    def recipient_result(self,event_id,recipient,status,error='',retry_in=0,*,coverage=None):
        with self.lock:
            self.db.execute("""
                UPDATE recipient_deliveries SET status=?,attempts=attempts+CASE WHEN ? IN ('pending','sent') THEN 1 ELSE 0 END,
                next_try=?,sent_at=CASE WHEN ?='sent' THEN ? ELSE sent_at END,error=?,coverage=?
                WHERE event_id=? AND recipient=?
                """, (status,status,time.time()+retry_in,status,time.time(),error,
                      json.dumps(coverage) if coverage is not None else None,event_id,recipient))
            self.db.commit()

    def cleanup(self,days):
        cutoff=time.time()-days*86400
        with self.lock:
            rows=self.db.execute('SELECT snapshot FROM events WHERE created<?',(cutoff,)).fetchall()
            for row in rows:
                (self.directory/'events'/row['snapshot']).unlink(missing_ok=True)
            self.db.execute('DELETE FROM incident_assessments WHERE event_id IN (SELECT id FROM events WHERE created<?)', (cutoff,))
            self.db.execute('DELETE FROM events WHERE created<?',(cutoff,))
            self.db.execute('DELETE FROM samples WHERE created<?',(cutoff,))
            self.db.execute('DELETE FROM recipient_deliveries WHERE created<?',(cutoff,))
            self.db.execute('DELETE FROM health_outbox WHERE created<?',(cutoff,))
            self.db.commit()
