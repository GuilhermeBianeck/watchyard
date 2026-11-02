import shutil
import subprocess
import threading
import time
from urllib.parse import quote

import cv2
import numpy as np


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
        self.detections = []
        self.detected_at = 0
        self.inference_ms = 0
        self.detected_sequence = -1
        self.last_error = None

    def start(self):
        threading.Thread(target=self.run, name=f"camera-{self.id}", daemon=True).start()

    def latest(self):
        with self.lock:
            return self.frame, self.captured_at, self.sequence

    def run(self):
        s = self.settings
        host = s.secret('NVR_HOST', '127.0.0.1')
        user = quote(s.secret('NVR_USERNAME', 'admin'), safe='')
        password = quote(s.secret('NVR_PASSWORD', ''), safe='')
        url = f"rtsp://{user}:{password}@{host}:554/Streaming/Channels/{self.id}02"
        hardware = True
        while not self.stop.is_set():
            args = [shutil.which('ffmpeg') or '/opt/homebrew/bin/ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-rtsp_transport', 'tcp', '-timeout', '10000000']
            if hardware:
                args += ['-hwaccel', 'videotoolbox']
            args += ['-i', url, '-an', '-sn', '-vf', f'fps=3,scale={self.WIDTH}:{self.HEIGHT}', '-pix_fmt', 'bgr24', '-f', 'rawvideo', 'pipe:1']
            got_frame = False
            try:
                self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=self.WIDTH*self.HEIGHT*3)
                def consume_errors(proc):
                    for raw in proc.stderr:
                        line = raw.decode(errors='replace').strip()
                        line = line.replace(url, '[NVR stream]')
                        password_value = s.secret('NVR_PASSWORD', '')
                        if password_value:
                            line = line.replace(password_value,'[redacted]').replace(quote(password_value,safe=''),'[redacted]')
                        self.last_error = line[-400:]
                threading.Thread(target=consume_errors,args=(self.process,),daemon=True).start()
                self.mode = 'VideoToolbox' if hardware else 'software'
                size = self.WIDTH*self.HEIGHT*3
                while not self.stop.is_set():
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
            if not got_frame and hardware:
                hardware = False
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

    def jpeg(self, annotated=True):
        frame, stamp, _ = self.latest()
        if frame is None or time.time()-stamp > 12:
            return None
        frame = frame.copy()
        if annotated and time.time()-self.detected_at < 3:
            for d in self.detections:
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
