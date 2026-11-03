"""Authenticated, shared HLS feeds, started only while a camera is watched."""
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import quote
import uuid

from .runtime import Runtime

SEGMENT = re.compile(r'^[0-9a-f]{12}-[0-9]{6,12}\.ts$')


class LiveFeed:
    FPS = 10
    IDLE_SECONDS = 20

    def __init__(self, camera, settings):
        self.camera, self.settings = camera, settings
        self.directory = settings.path / 'live' / str(camera)
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.lock = threading.RLock()
        self.process = None
        self.generation = ''
        self.requested = 0
        self.started = 0
        self.retry_after = 0
        self.software = Runtime.read().decoder == 'software'
        self.clear_files()

    def clear_files(self):
        for f in self.directory.iterdir():
            if f.is_file(): f.unlink(missing_ok=True)

    def command(self):
        s = self.settings
        user = quote(s.secret('NVR_USERNAME', 'admin'), safe='')
        password = quote(s.secret('NVR_PASSWORD', ''), safe='')
        url = f"rtsp://{user}:{password}@{s.secret('NVR_HOST','127.0.0.1')}:554/Streaming/Channels/{self.camera}02"
        args = [shutil.which('ffmpeg') or 'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                '-rtsp_transport', 'tcp', '-timeout', '10000000',
                '-analyzeduration', '1000000', '-probesize', '262144']
        if not self.software: args += ['-hwaccel', 'videotoolbox']
        args += ['-i', url, '-an', '-sn', '-vf', 'scale=w=1280:h=720:force_original_aspect_ratio=decrease:force_divisible_by=2',
                 '-r', str(self.FPS), '-c:v', 'libx264' if self.software else 'h264_videotoolbox']
        if self.software:
            args += ['-preset', 'veryfast', '-tune', 'zerolatency', '-threads', '2']
        else:
            args += ['-realtime', '1']
        args += ['-b:v', '1000k', '-maxrate', '1200k', '-bufsize', '2000k', '-pix_fmt', 'yuv420p',
                 '-g', str(self.FPS), '-bf', '0', '-force_key_frames', 'expr:gte(t,n_forced*1)',
                 '-f', 'hls', '-hls_time', '1', '-hls_list_size', '5', '-hls_delete_threshold', '3',
                 '-hls_flags', 'delete_segments+omit_endlist+independent_segments+temp_file',
                 '-hls_segment_filename', str(self.directory / (self.generation + '-%06d.ts')),
                 '-y', str(self.directory / 'index.m3u8')]
        return args

    def running(self):
        return self.process is not None and self.process.poll() is None

    def ensure(self):
        with self.lock:
            now = time.monotonic()
            self.requested = now
            index = self.directory / 'index.m3u8'
            stale = self.running() and now - self.started > 12 and (
                not index.exists() or time.time() - index.stat().st_mtime > 8)
            if stale: self.close()
            if self.running() or now < self.retry_after: return
            if self.process is not None:
                # Failed hardware startup gets one software fallback on the next attempt.
                if not index.exists(): self.software = True
                self.close()
            self.clear_files()
            self.generation = uuid.uuid4().hex[:12]
            self.started = now
            self.retry_after = now + 3
            try:
                # Never log subprocess arguments or stderr: the RTSP URL contains credentials.
                self.process = subprocess.Popen(self.command(), stdin=subprocess.DEVNULL,
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                self.process = None

    def playlist(self, wait=10):
        self.ensure()
        deadline = time.monotonic() + wait
        while True:
            with self.lock:
                try:
                    path = self.directory / 'index.m3u8'
                    text = path.read_text()
                    names = [line.strip() for line in text.splitlines() if line and not line.startswith('#')]
                    if (self.running() and time.time() - path.stat().st_mtime < 6 and
                            text.startswith('#EXTM3U') and '://' not in text and 'URI=' not in text and names and
                            all(SEGMENT.fullmatch(n) and n.startswith(self.generation + '-') for n in names)):
                        return text
                except (OSError, UnicodeError):
                    pass
                if not self.running() or time.monotonic() >= deadline: return None
            time.sleep(.15)

    def segment(self, filename):
        with self.lock:
            if not SEGMENT.fullmatch(filename) or not filename.startswith(self.generation + '-'):
                return None
            path = self.directory / filename
            if not path.is_file(): return None
            self.requested = time.monotonic()
            return path

    def reap(self):
        with self.lock:
            if self.process is not None and time.monotonic() - self.requested > self.IDLE_SECONDS:
                self.close()
                self.clear_files()

    def close(self):
        with self.lock:
            proc, self.process = self.process, None
            if proc is not None:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=3)
                except OSError:
                    pass


class Live:
    def __init__(self, settings, stop):
        self.stop = stop
        self.feeds = {i: LiveFeed(i, settings) for i in range(1, 5)}
        self.thread = None

    def start(self):
        def collect():
            while not self.stop.wait(2):
                for feed in self.feeds.values(): feed.reap()
        self.thread = threading.Thread(target=collect, name='live-view-cleanup', daemon=True)
        self.thread.start()

    def status(self):
        return {'fps': LiveFeed.FPS, 'active_cameras': [i for i, f in self.feeds.items() if f.running()]}

    def close(self):
        for feed in self.feeds.values():
            feed.close(); feed.clear_files()
        if self.thread: self.thread.join(timeout=3)
