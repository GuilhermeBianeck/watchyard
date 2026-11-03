"""Optional local plate readings from a short main-stream burst after vehicle events."""
from collections import Counter
import json
import logging
from pathlib import Path
import queue
import re
import subprocess
import tempfile
import threading
import time

from .sources import CameraSources

log = logging.getLogger(__name__)
PLATE = re.compile(
    r'(?:[A-Z]{2}[0-9]{4}|[0-9]{4}[A-Z]{2}|[0-9]{2}[A-Z]{2}[0-9]{2}|[A-Z]{2}[0-9]{2}[A-Z]{2})',
    re.ASCII,
)


def normalize(text):
    value = re.sub(r'[ -]', '', text.strip().upper())
    if PLATE.fullmatch(value):
        return '-'.join(value[index:index+2] for index in (0, 2, 4))
    return None


def consensus(frames):
    votes = Counter()
    for frame in frames:
        votes.update({plate for text in frame if (plate := normalize(text))})
    # Reject ambiguous scenes with two persistent readings.
    confirmed = [plate for plate, count in votes.items() if count >= 2]
    return confirmed[0] if len(confirmed) == 1 else None


class Plates:
    def __init__(self, settings, store, stop):
        self.settings, self.store, self.stop = settings, store, stop
        self.helper = settings.path / 'runtime' / 'plate-ocr'
        self.queue = queue.Queue(maxsize=2)

    def start(self):
        if self.helper.is_file() and any(c.get('plate_zone') for c in self.settings.snapshot()['cameras']):
            threading.Thread(target=self.work, name='plate-recognition', daemon=True).start()

    def submit(self, camera, event_id):
        if not camera.get('plate_zone') or not self.helper.is_file():
            return
        try:
            self.queue.put_nowait((camera, event_id, time.monotonic()))
        except queue.Full:
            log.info('Plate reader busy; skipped one vehicle event')

    def work(self):
        while not self.stop.is_set():
            try:
                camera, event_id, queued = self.queue.get(timeout=1)
            except queue.Empty:
                continue
            if time.monotonic() - queued > 8:
                continue
            try:
                plate = self.read(camera)
                if plate and not self.stop.is_set():
                    self.store.save_plate(event_id, plate)
            except (OSError, ValueError, subprocess.SubprocessError):
                log.warning('Plate scan failed for camera %s', camera['id'])

    def read(self, camera):
        sources = CameraSources(self.settings)
        if sources.override(camera['id']):
            return None
        channel = camera.get('channel') or camera['id']
        url = f'{sources.recorder_base()}/Streaming/Channels/{channel}01'
        left, top, right, bottom = camera['plate_zone']
        crop = f'crop=iw*{right-left}:ih*{bottom-top}:iw*{left}:ih*{top}'
        with tempfile.TemporaryDirectory(prefix='watchyard-plates-') as directory:
            target = Path(directory) / 'frame-%02d.jpg'
            result = subprocess.run(
                ['ffmpeg', '-nostdin', '-loglevel', 'error', '-rtsp_transport', 'tcp',
                 '-timeout', '5000000', '-i', url, '-ss', '1.5', '-an',
                 '-vf', f'fps=2,{crop}', '-frames:v', '6', '-q:v', '3', str(target)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=14,
            )
            frames = sorted(Path(directory).glob('frame-*.jpg'))
            if result.returncode or len(frames) < 2 or self.stop.is_set():
                return None
            result = subprocess.run([str(self.helper), *map(str, frames)], capture_output=True,
                                    check=True, timeout=150)
            return consensus(json.loads(result.stdout))
