"""On-demand recorder replay, with a bounded cache and explicitly kept clips."""
import datetime as dt
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET

import requests
from requests.auth import HTTPDigestAuth

from .runtime import Runtime
from .sources import CameraSources

log = logging.getLogger('watchyard.replay')
CLIP_ID = re.compile(r'^[0-9a-f]{32}$')


class ReplayError(RuntimeError):
    pass


def utc_text(stamp, compact=False):
    return dt.datetime.fromtimestamp(stamp, dt.timezone.utc).strftime(
        '%Y%m%dT%H%M%SZ' if compact else '%Y-%m-%dT%H:%M:%SZ')


def parse_time(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Recorder timestamp has no timezone')
    return parsed.timestamp()


def xml_text(node, name, default=''):
    return next((e.text or default for e in node.iter()
                 if e.tag.split('}')[-1] == name), default)


class Recorder:
    def __init__(self, settings):
        self.settings = settings
        self.playback_offset = 0
        self.sources = CameraSources(settings)

    def request(self, method, path, body=None):
        s = requests.Session()
        s.trust_env = False
        s.auth = HTTPDigestAuth(self.settings.secret('NVR_USERNAME', 'admin'),
                               self.settings.secret('NVR_PASSWORD', ''))
        try:
            with s, s.request(method, 'http://' + self.settings.secret('NVR_HOST', '127.0.0.1') + path,
                              data=body, headers={'Content-Type': 'application/xml'},
                              timeout=(5, 12), allow_redirects=False, stream=True) as response:
                if response.status_code in (401, 403):
                    raise ReplayError('The recorder rejected its configured credentials.')
                if response.status_code != 200:
                    raise ReplayError('The recorder could not search its recordings. Try again shortly.')
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > 2 * 1024**2:
                        raise ReplayError('The recorder returned an unexpected search response.')
                return ET.fromstring(data)
        except (requests.RequestException, ET.ParseError):
            raise ReplayError('Cannot reach the recorder. Check its connection and try again.') from None

    def track(self, camera):
        track = self.sources.track(camera)
        if track is None:
            raise ReplayError('Recorder replay is not configured for this camera.')
        return track

    def search(self, camera, start, end):
        track = self.track(camera)
        clock = self.request('GET', '/ISAPI/System/time')
        try:
            local = dt.datetime.fromisoformat(xml_text(clock, 'localTime').replace('Z', '+00:00'))
            if local.tzinfo is None:raise ValueError('Missing recorder timezone')
            offset = local.timestamp() - time.time()
            # This recorder's ISAPI/RTSP APIs label local wall time with a Z suffix.
            # Keep application timestamps UTC and translate only at this boundary.
            self.playback_offset = local.utcoffset().total_seconds()
        except (ValueError, OverflowError):
            raise ReplayError('The recorder did not report a valid clock.') from None
        if abs(offset) > 30:
            raise ReplayError('The recorder clock differs from this server. Correct the recorder clock before replaying alerts.')
        root = ET.Element('CMSearchDescription')
        ET.SubElement(root, 'searchID').text = str(uuid.uuid4())
        tracks = ET.SubElement(root, 'trackList')
        ET.SubElement(tracks, 'trackID').text = str(track)
        span = ET.SubElement(ET.SubElement(root, 'timeSpanList'), 'timeSpan')
        ET.SubElement(span, 'startTime').text = utc_text(start + self.playback_offset)
        ET.SubElement(span, 'endTime').text = utc_text(end + self.playback_offset)
        ET.SubElement(root, 'maxResults').text = '100'
        # The spelling is part of the recorder's ISAPI schema.
        ET.SubElement(root, 'searchResultPostion').text = '0'
        metadata = ET.SubElement(root, 'metadataList')
        ET.SubElement(metadata, 'metadataDescriptor').text = '//recordType.meta.std-cgi.com'
        result = self.request('POST', '/ISAPI/ContentMgmt/search', ET.tostring(root))
        if xml_text(result, 'responseStatus').lower() != 'true':
            raise ReplayError('The recorder could not search this recording.')
        spans = []
        for item in result.iter():
            if item.tag.split('}')[-1] != 'searchMatchItem':
                continue
            if xml_text(item, 'trackID') != str(track):
                continue
            try:
                a = parse_time(xml_text(item, 'startTime')) - self.playback_offset
                b = parse_time(xml_text(item, 'endTime')) - self.playback_offset
                if a < end and b > start:
                    spans.append((max(start, a), min(end, b)))
            except (ValueError, OverflowError):
                continue
        return sorted(spans)

    def replay_url(self, camera, start, end):
        # Construct our own URI: never follow a host or credentials returned by a recorder.
        return (f'{self.sources.recorder_base()}/Streaming/tracks/{self.track(camera)}/'
                f'?starttime={utc_text(start + self.playback_offset, True)}&endtime={utc_text(end + self.playback_offset, True)}')


class Clips:
    CACHE_BYTES = 512 * 1024**2
    SAVED_BYTES = 2 * 1024**3
    MIN_FREE = 1024**3
    CACHE_SECONDS = 86400
    MAX_AFTER_ALERT = 300
    RECORDER_SETTLE = 15
    SEEK_ALLOWANCE = 6

    def __init__(self, settings, stop, store=None):
        self.settings, self.stop = settings, stop
        self.store = store
        self.directory = settings.path / 'clips'
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.lock = threading.RLock()
        self.recorder = Recorder(settings)
        self.db = sqlite3.connect(settings.path / 'clips.db', check_same_thread=False, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS clips (
            id TEXT PRIMARY KEY,event_id TEXT UNIQUE,camera INTEGER,camera_name TEXT,label TEXT,
            event_created REAL,start REAL,end REAL,created REAL,accessed REAL,not_before REAL,
            state TEXT,error TEXT DEFAULT '',warning TEXT DEFAULT '',saved INTEGER DEFAULT 0,
            size INTEGER DEFAULT 0,duration REAL DEFAULT 0)''')
        self.db.execute("UPDATE clips SET state='queued' WHERE state='preparing'")
        self.db.commit()
        self.process = None
        self.thread = None

    def get(self, key):
        if not CLIP_ID.fullmatch(key):
            return None
        with self.lock:
            row = self.db.execute('SELECT * FROM clips WHERE id=?', (key,)).fetchone()
        return dict(row) if row else None

    def public(self, clip):
        keys = ('id', 'event_id', 'camera', 'camera_name', 'label', 'event_created',
                'start', 'end', 'created', 'state', 'error', 'warning', 'saved', 'size', 'duration')
        return {k: clip[k] for k in keys} | {'waiting_for_recording': clip['not_before'] > time.time()}

    def saved(self):
        with self.lock:
            rows = self.db.execute('SELECT * FROM clips WHERE saved=1 ORDER BY event_created DESC').fetchall()
        return [self.public(dict(r)) for r in rows]

    def window(self, event):
        created = event['created']
        if event.get('first_seen') is not None and event.get('last_seen') is not None:
            # Bound both ends even for long-lived tracks or delayed confirmation.
            first = max(created-60, min(event['first_seen'], created))
            end = min(created+self.MAX_AFTER_ALERT, max(created+30, event['last_seen']+15))
            return first-15, end
        if event['label'] == 'cat':
            # Older alerts did not record observations. Give feeding visits more context.
            return created-30, created+180
        return created-10, created+30

    def request(self, event):
        now = time.time()
        with self.lock:
            row = self.db.execute('SELECT * FROM clips WHERE event_id=?', (event['id'],)).fetchone()
            start, end = self.window(event)
            if row:
                in_progress = row['state'] in ('queued', 'preparing')
                ready = row['state'] == 'ready' and self.path(row['id']).is_file()
                covers_window = row['start'] <= start and row['end'] >= end
                if in_progress or (ready and (row['saved'] or covers_window)):
                    self.touch(row['id'])
                    return self.get(row['id'])
            self.recorder.track(event['camera'])
            count = self.db.execute("SELECT count(*) FROM clips WHERE state IN ('queued','preparing')").fetchone()[0]
            if count >= 8:
                raise ReplayError('The replay queue is full. Try again after a clip finishes.')
            if shutil.disk_usage(self.directory).free < self.MIN_FREE:
                raise ReplayError('The server needs at least 1 GB of free space to prepare a replay.')
            key = row['id'] if row else uuid.uuid4().hex
            not_before = end + self.RECORDER_SETTLE
            if row:
                self.db.execute("UPDATE clips SET state='queued',error='',warning='',start=?,end=?,not_before=?,accessed=? WHERE id=?",
                                (start, end, not_before, now, key))
            else:
                self.db.execute('''INSERT INTO clips
                    (id,event_id,camera,camera_name,label,event_created,start,end,created,accessed,not_before,state)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,'queued')''',
                    (key, event['id'], event['camera'], event['camera_name'], event['label'],
                     event['created'], start, end, now, now, not_before))
            self.db.commit()
            return self.get(key)

    def keep(self, key, saved):
        with self.lock:
            clip = self.get(key)
            if not clip or clip['state'] != 'ready' or not self.path(key).is_file():
                raise ReplayError('Prepare the replay before keeping it.')
            total = self.db.execute('SELECT coalesce(sum(size),0) FROM clips WHERE saved=1 AND id!=?', (key,)).fetchone()[0]
            if saved and total + clip['size'] > self.SAVED_BYTES:
                raise ReplayError('Saved clips have reached 2 GB. Download a clip and remove it from Saved to make room.')
            self.db.execute('UPDATE clips SET saved=?,accessed=? WHERE id=?', (int(saved), time.time(), key))
            self.db.commit()
            return self.get(key)

    def path(self, key, poster=False):
        if not CLIP_ID.fullmatch(key):
            raise ValueError('Invalid clip ID')
        return self.directory / (key + ('.jpg' if poster else '.mp4'))

    def touch(self, key):
        with self.lock:
            self.db.execute('UPDATE clips SET accessed=? WHERE id=?', (time.time(), key))
            self.db.commit()

    def cleanup(self):
        with self.lock:
            rows = self.db.execute("SELECT * FROM clips WHERE saved=0 AND state='ready' ORDER BY accessed DESC").fetchall()
            used = 0
            for row in rows:
                used += row['size']
                if time.time() - row['accessed'] < self.CACHE_SECONDS and used <= self.CACHE_BYTES:
                    continue
                for poster in (False, True):
                    self.path(row['id'], poster).unlink(missing_ok=True)
                self.db.execute("UPDATE clips SET state='expired',size=0 WHERE id=?", (row['id'],))
            self.db.execute("DELETE FROM clips WHERE saved=0 AND state IN ('expired','failed','unavailable') AND accessed<?",
                            (time.time() - 7 * 86400,))
            self.db.commit()

    def run_process(self, args, timeout):
        # No stderr/URL is logged: the input URL necessarily contains recorder credentials.
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.process = proc
        deadline = time.monotonic() + timeout
        try:
            while proc.poll() is None:
                if self.stop.wait(.25) or time.monotonic() > deadline:
                    proc.terminate()
                    try: proc.wait(timeout=3)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                    raise ReplayError('Replay preparation stopped. Try again shortly.')
            data = proc.stdout.read()
            if proc.returncode:
                raise ReplayError('The recorder could not return a playable clip for this moment. Try again shortly.')
            return data
        finally:
            self.process = None
            proc.stdout.close()

    def prepare(self, clip):
        spans = self.recorder.search(clip['camera'], clip['start'], clip['end'])
        if not any(a <= clip['event_created'] <= b for a, b in spans):
            return 'unavailable', 'No recording was found at this alert. It may have been overwritten or not recorded.'
        if shutil.disk_usage(self.directory).free < self.MIN_FREE:
            raise ReplayError('The server needs at least 1 GB of free space to prepare a replay.')
        cursor = clip['start']
        for a, b in spans:
            if a > cursor + 2: break
            cursor = max(cursor, b)
        warning = '' if cursor >= clip['end'] - 2 else 'The recorder has gaps in this replay window.'
        runtime = Runtime.read()
        ffmpeg = shutil.which('ffmpeg') or 'ffmpeg'
        part = self.directory / (clip['id'] + '.part.mp4')
        poster = self.directory / (clip['id'] + '.part.jpg')
        args = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
                '-rtsp_transport', 'tcp', '-timeout', '10000000']
        if runtime.decoder == 'videotoolbox':
            args += ['-hwaccel', 'videotoolbox']
        requested_duration = clip['end'] - clip['start']
        capture_duration = requested_duration + self.SEEK_ALLOWANCE
        args += ['-i', self.recorder.replay_url(clip['camera'], clip['start'], clip['end'] + self.SEEK_ALLOWANCE),
                 '-t', str(capture_duration), '-an', '-sn', '-vf',
                 'scale=w=1280:h=720:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1',
                 '-r', '15', '-c:v', 'h264_videotoolbox' if runtime.decoder == 'videotoolbox' else 'libx264']
        if runtime.decoder != 'videotoolbox':
            args += ['-preset', 'veryfast', '-threads', '2']
        args += ['-b:v', '1500k', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                 '-fs', str(80 * 1024**2), '-y', str(part)]
        try:
            self.run_process(args, max(100, capture_duration + 45))
            data = self.run_process([shutil.which('ffprobe') or 'ffprobe', '-v', 'error',
                                     '-show_entries', 'format=duration:stream=codec_name',
                                     '-of', 'json', str(part)], 10)
            info = json.loads(data)
            duration = float(info['format']['duration'])
            if duration < 4 or not any(s['codec_name'] == 'h264' for s in info['streams']):
                raise ReplayError('The recorder returned an incomplete clip. Try again shortly.')
            if duration < requested_duration - 2:
                warning = 'The recorder returned a shorter replay. Some context may be missing.'
            self.run_process([ffmpeg, '-nostdin', '-loglevel', 'error', '-i', str(part),
                              '-frames:v', '1', '-q:v', '3', '-y', str(poster)], 15)
            with self.lock:
                part.replace(self.path(clip['id']))
                poster.replace(self.path(clip['id'], True))
                self.db.execute("UPDATE clips SET state='ready',error='',warning=?,size=?,duration=?,accessed=? WHERE id=?",
                                (warning, self.path(clip['id']).stat().st_size, duration, time.time(), clip['id']))
                self.db.commit()
        finally:
            part.unlink(missing_ok=True)
            poster.unlink(missing_ok=True)
        return 'ready', ''

    def work_once(self):
        with self.lock:
            rows = self.db.execute("SELECT * FROM clips WHERE state='queued' AND not_before<=? ORDER BY created",
                                   (time.time(),)).fetchall()
            clip = None
            for row in rows:
                clip = dict(row)
                event = self.store.event(clip['event_id']) if self.store else None
                if event:
                    start, end = self.window(event)
                    not_before = end + self.RECORDER_SETTLE
                    self.db.execute('UPDATE clips SET start=?,end=?,not_before=? WHERE id=?',
                                    (start, end, not_before, clip['id']))
                    clip.update(start=start, end=end, not_before=not_before)
                    if not_before > time.time():
                        clip = None
                        continue
                self.db.execute("UPDATE clips SET state='preparing' WHERE id=?", (clip['id'],))
                break
            self.db.commit()
            if clip is None:
                return False
        try:
            state, error = self.prepare(clip)
        except Exception as exc:
            state, error = ('queued', '') if self.stop.is_set() else (
                'failed', str(exc) if isinstance(exc, ReplayError) else 'Replay preparation failed. Try again shortly.')
            log.warning('Replay job failed (%s)', type(exc).__name__)
        with self.lock:
            self.db.execute('UPDATE clips SET state=?,error=? WHERE id=?', (state, error, clip['id']))
            self.db.commit()
        self.cleanup()
        return True

    def start(self):
        self.cleanup()
        def work():
            while not self.stop.is_set():
                if not self.work_once(): self.stop.wait(1)
        self.thread = threading.Thread(target=work, name='recorder-replay', daemon=True)
        self.thread.start()

    def close(self):
        if self.thread: self.thread.join(timeout=8)
