import sqlite3
import threading
import time
import uuid


class Store:
    def __init__(self, directory):
        self.directory = directory
        self.lock = threading.RLock()
        self.db = sqlite3.connect(directory / "events.db", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, created REAL, camera INTEGER, camera_name TEXT,
            label TEXT, confidence REAL, snapshot TEXT, status TEXT,
            attempts INTEGER DEFAULT 0, next_try REAL DEFAULT 0, detail TEXT DEFAULT '')""")
        self.db.commit()

    def add(self, camera, label, confidence, snapshot, status="pending", detail=""):
        key = uuid.uuid4().hex
        with self.lock:
            self.db.execute("INSERT INTO events (id,created,camera,camera_name,label,confidence,snapshot,status,detail) VALUES (?,?,?,?,?,?,?,?,?)", (key,time.time(),camera['id'],camera['name'],label,confidence,snapshot,status,detail))
            self.db.commit()
        return key

    def recent(self, limit=50):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY created DESC LIMIT ?", (limit,))]

    def pending(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM events WHERE status='pending' AND next_try<=? ORDER BY created LIMIT 4", (time.time(),))]

    def mark(self, key, status, detail="", retry_in=0):
        with self.lock:
            self.db.execute("UPDATE events SET status=?, detail=?, attempts=attempts+1, next_try=? WHERE id=?", (status,detail,time.time()+retry_in,key))
            self.db.commit()

    def cleanup(self, days):
        with self.lock:
            rows = self.db.execute("SELECT snapshot FROM events WHERE created<?", (time.time()-days*86400,)).fetchall()
            for row in rows:
                (self.directory / "events" / row['snapshot']).unlink(missing_ok=True)
            self.db.execute("DELETE FROM events WHERE created<?", (time.time()-days*86400,))
            self.db.commit()
