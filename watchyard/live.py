"""Authenticated, shared HLS feeds, started only while a camera is watched."""
import re
import shutil
import subprocess
import threading
import time
import uuid

from .capture import Camera, read_frame
from .runtime import Runtime
from .sources import CameraSources

SEGMENT = re.compile(r'^[0-9a-f]{12}-[0-9]{6,12}\.ts$')


class LiveFeed:
    FPS = 10
    IDLE_SECONDS = 20

    def __init__(self, camera, settings, capture=None):
        self.camera, self.settings = camera, settings
        self.capture = capture
        self.shared_failed = False
        self.shared_rate = None
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

    def command(self, shared_rate=None):
        url = CameraSources(self.settings).stream(self.camera)
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
        if shared_rate is not None:
            input_end = args.index('-i') + 2
            args[input_end:input_end] = ['-map', '0:v:0']
            args += ['-map', '0:v:0', '-an', '-sn', '-vf',
                     f'fps={shared_rate},scale={Camera.WIDTH}:{Camera.HEIGHT}',
                     '-pix_fmt', 'bgr24', '-f', 'rawvideo', 'pipe:1']
        return args

    def running(self):
        return self.process is not None and self.process.poll() is None

    def ensure(self):
        with self.lock:
            now = time.monotonic()
            self.requested = now
            index = self.directory / 'index.m3u8'
            rate = self.settings.snapshot()['inference_fps'] if self.capture else None
            stale = self.running() and now - self.started > 12 and (
                not index.exists() or time.time() - index.stat().st_mtime > 8)
            if stale or (self.running() and self.shared_rate is not None and rate != self.shared_rate):
                self.shared_failed |= stale and self.shared_rate is not None
                self.close()
            if self.running() or now < self.retry_after:
                return
            if self.process is not None:
                if self.shared_rate is not None:
                    self.shared_failed = True
                elif not index.exists():
                    self.software = True
                self.close()
            self.clear_files()
            self.generation = uuid.uuid4().hex[:12]
            self.started = now
            self.retry_after = now + 3
            self.shared_rate = rate if not self.shared_failed else None
            try:
                # Do not log subprocess arguments or stderr. The RTSP URL contains credentials.
                pipe = subprocess.PIPE if self.shared_rate is not None else subprocess.DEVNULL
                proc = subprocess.Popen(self.command(self.shared_rate), stdin=subprocess.DEVNULL,
                                        stdout=pipe, stderr=subprocess.DEVNULL,
                                        bufsize=Camera.WIDTH * Camera.HEIGHT * 3)
                self.process = proc
                if self.shared_rate is not None:
                    threading.Thread(target=self.read_shared, args=(proc,),
                                     name=f'live-analysis-{self.camera}', daemon=True).start()
            except OSError:
                self.process = None
                self.shared_failed |= self.shared_rate is not None

    def read_shared(self, proc):
        try:
            with proc.stdout as stream:
                while (frame := read_frame(stream)) is not None:
                    with self.lock:
                        if self.process is not proc:
                            break
                        if (self.directory / 'index.m3u8').exists():
                            wanted = time.monotonic() - self.requested <= self.IDLE_SECONDS
                            self.capture.publish_shared(proc, frame, wanted=wanted)
        finally:
            self.capture.release_shared(proc)

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
            idle = time.monotonic() - self.requested
            if self.process is None or idle <= self.IDLE_SECONDS:
                return
            if (self.shared_rate is not None and self.running()
                    and not self.capture.resume_local(self.process) and idle <= self.IDLE_SECONDS + 12):
                return
            self.close()
            self.clear_files()

    def close(self):
        with self.lock:
            proc, self.process = self.process, None
            if proc is not None:
                if self.shared_rate is not None:
                    self.capture.release_shared(proc)
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=3)
                except OSError:
                    pass


class Live:
    def __init__(self, settings, stop, cameras=None):
        self.stop = stop
        self.feeds = {
            c['id']: LiveFeed(c['id'], settings, (cameras or {}).get(c['id']) if c.get('shared_ingest') else None)
            for c in settings.snapshot()['cameras']
        }
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
