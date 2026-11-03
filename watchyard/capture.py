import shutil
import subprocess
import threading
import time

import cv2
import numpy as np
from .runtime import Runtime
from .sources import CameraSources
from .overlays import Overlays


class Camera:
    WIDTH, HEIGHT = 960, 540

    def __init__(self, camera_id, settings, stop):
        self.id, self.settings, self.stop = camera_id, settings, stop
        self.lock = threading.Lock()
        self.frame = None
        self.captured_at = 0
        self.sequence = 0
        self.process = None
        self.mode = "starting"
        self.reconnects = 0
        self.overlays = Overlays()
        self.detected_at = 0
        self.inference_ms = 0
        self.detected_sequence = -1
        self.analysed_frames = 0
        self.last_error = None

    def start(self):
        threading.Thread(target=self.run, name=f"camera-{self.id}", daemon=True).start()

    def latest(self):
        with self.lock:
            return self.frame, self.captured_at, self.sequence

    def run(self):
        s = self.settings
        url = CameraSources(s).stream(self.id)
        hardware = Runtime.read().decoder == 'videotoolbox'
        while not self.stop.is_set():
            sampling = max(1, min(2, s.snapshot()['inference_fps']))
            reconfigured = False
            args = [shutil.which('ffmpeg') or 'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-rtsp_transport', 'tcp', '-timeout', '10000000']
            if hardware:
                args += ['-hwaccel', 'videotoolbox']
            args += ['-i', url, '-an', '-sn', '-vf', f'fps={sampling:g},scale={self.WIDTH}:{self.HEIGHT}', '-pix_fmt', 'bgr24', '-f', 'rawvideo', 'pipe:1']
            got_frame = False
            try:
                self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=self.WIDTH*self.HEIGHT*3)
                self.mode = 'VideoToolbox' if hardware else 'software'
                size = self.WIDTH*self.HEIGHT*3
                while not self.stop.is_set():
                    if max(1, min(2, s.snapshot()['inference_fps'])) != sampling:
                        reconfigured = True
                        break
                    parts, count = [], 0
                    while count < size and not self.stop.is_set():
                        chunk = self.process.stdout.read(size-count)
                        if not chunk:
                            break
                        parts.append(chunk)
                        count += len(chunk)
                    if count != size:
                        break
                    frame = np.frombuffer(b''.join(parts), dtype=np.uint8).reshape((self.HEIGHT,self.WIDTH,3)).copy()
                    with self.lock:
                        self.frame, self.captured_at = frame, time.time()
                        self.sequence += 1
                    self.last_error = None
                    got_frame = True
            except (OSError, ValueError):
                self.mode = 'reconnecting'
            finally:
                self.close()
            if reconfigured:
                continue
            if not got_frame and hardware:
                hardware = False
            self.last_error = "Camera stream disconnected; reconnecting"
            self.reconnects += 1
            self.stop.wait(4)

    def close(self):
        proc = self.process
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            except OSError:
                pass

    def publish_detections(self, detections, sequence):
        with self.lock:
            self.overlays.update(detections, time.monotonic())
            self.detected_at = time.time()
            self.detected_sequence = sequence

    def display_detections(self, config):
        with self.lock:
            if not config['enabled'] or time.time()-self.captured_at >= 6:
                return []
            return self.overlays.visible(time.monotonic(), config['labels'])

    def jpeg(self, annotated=True):
        frame, stamp, _ = self.latest()
        if frame is None or time.time()-stamp > 12:
            return None
        frame = frame.copy()
        if annotated:
            config = CameraSources(self.settings).camera(self.id)
            for d in self.display_detections(config):
                draw_detection(frame, d)
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return encoded.tobytes() if ok else None


def draw_detection(frame, detection):
    h,w = frame.shape[:2]
    a,b,c,d = [int(v*(w if i%2==0 else h)) for i,v in enumerate(detection['box'])]
    color = (105,205,155)
    cv2.rectangle(frame, (a,b), (c,d), color, 2)
    text = f"{detection['label']} {detection['confidence']:.0%}"
    cv2.putText(frame,text,(a,max(20,b-8)),cv2.FONT_HERSHEY_SIMPLEX,0.6,color,2)
