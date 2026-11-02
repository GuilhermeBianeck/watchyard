import logging
import os
import threading
import time
import uuid

import cv2
import psutil

from .capture import Camera, draw_detection
from .rules import Tracker
from .store import Store
from .telegram import Telegram

log = logging.getLogger('watchyard')


class Service:
    def __init__(self, settings):
        self.settings = settings
        self.stop = threading.Event()
        self.store = Store(settings.path)
        self.cameras = {i:Camera(i,settings,self.stop) for i in range(1,5)}
        self.trackers = {i:Tracker() for i in self.cameras}
        self.telegram = Telegram(settings,self)
        self.started = time.time()
        self.detector = 'loading'
        self.detector_error = None
        self.model = None
        self.previous_online = {}
        self.monitor_thread = None

    def start(self):
        for camera in self.cameras.values():
            camera.start()
        self.telegram.start()
        threading.Thread(target=self.detect,name='detector',daemon=True).start()
        self.monitor_thread = threading.Thread(target=self.monitor,name='health-monitor',daemon=True)
        self.monitor_thread.start()

    def camera_config(self, camera_id):
        return next(c for c in self.settings.snapshot()['cameras'] if c['id']==camera_id)

    def load_model(self):
        os.environ['YOLO_CONFIG_DIR'] = str(self.settings.path/'ultralytics')
        os.environ['YOLO_AUTOINSTALL'] = 'false'
        from ultralytics import YOLO
        model_path = self.settings.path/'models/yolo11n.mlpackage'
        if not model_path.exists():
            raise RuntimeError('Core ML model missing. Run scripts/prepare_model.py.')
        self.model = YOLO(str(model_path), task='detect')
        # Force compile/warm-up now so status never says ready before inference works.
        import numpy as np
        self.model.predict(np.zeros((540,960,3),dtype=np.uint8), verbose=False, imgsz=640)
        self.detector = 'YOLO11 nano · Core ML'
        self.detector_error = None

    def detect(self):
        while not self.stop.is_set() and self.model is None:
            try:
                self.load_model()
            except Exception as exc:
                self.model = None
                self.detector = 'unavailable'
                self.detector_error = str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
                log.error('Detector load failed: %s',self.detector_error)
                self.stop.wait(30)
        next_due = {i:0.0 for i in self.cameras}
        while not self.stop.is_set():
            config = self.settings.snapshot()
            for c in config['cameras']:
                camera = self.cameras[c['id']]
                if not c['enabled'] or time.monotonic() < next_due[c['id']]:
                    continue
                frame, captured, sequence = camera.latest()
                if frame is None or time.time()-captured > 6 or sequence == camera.detected_sequence:
                    continue
                start = time.perf_counter()
                try:
                    result = self.model.predict(frame, conf=config['confidence'], classes=[0,2,15,16], imgsz=640, verbose=False)[0]
                    h,w = frame.shape[:2]
                    detections = []
                    for box in result.boxes:
                        label = result.names[int(box.cls[0])]
                        if label not in c['labels']:
                            continue
                        coords = box.xyxy[0].cpu().tolist()
                        detections.append({'label':label,'confidence':float(box.conf[0]),'box':[max(0,min(1,v/(w if i%2==0 else h))) for i,v in enumerate(coords)]})
                    camera.detections = detections
                    camera.detected_at = time.time()
                    camera.detected_sequence = sequence
                    camera.inference_ms = round((time.perf_counter()-start)*1000,1)
                    events = self.trackers[c['id']].update(detections,time.monotonic(),c['zone'],config['confirmation_frames'])
                    for event in events:
                        self.record(c,frame,event,config)
                    self.detector_error = None
                except Exception as exc:
                    self.detector_error = type(exc).__name__
                    log.error('Inference failed: %s',self.detector_error)
                    self.stop.wait(2)
                next_due[c['id']] = time.monotonic()+1/max(0.5,config['inference_fps'])
            self.stop.wait(0.02)

    def record(self, camera, frame, event, config):
        image = frame.copy()
        draw_detection(image,event)
        name = uuid.uuid4().hex+'.jpg'
        ok = cv2.imwrite(str(self.settings.path/'events'/name),image,[cv2.IMWRITE_JPEG_QUALITY,90])
        if not ok:
            raise RuntimeError('Could not save event snapshot')
        status = 'pending'
        if not config['enabled'] or config['muted_until'] > time.time():
            status = 'muted'
        elif not self.telegram.paired():
            status = 'unpaired'
        self.store.add(camera,event['label'],event['confidence'],name,status)
        log.info('Confirmed %s on camera %s (%s)',event['label'],camera['id'],status)

    def status(self):
        now = time.time()
        config = self.settings.snapshot()
        cameras = []
        for c in config['cameras']:
            camera = self.cameras[c['id']]
            cameras.append({**c,'online':now-camera.captured_at<12,'captured_at':camera.captured_at,'detected_at':camera.detected_at,'inference_ms':camera.inference_ms,'decoder':camera.mode,'reconnects':camera.reconnects,'error':camera.last_error,'detections':camera.detections if now-camera.detected_at<6 else []})
        process = psutil.Process()
        children = process.children(recursive=True)
        ram = process.memory_info().rss
        for child in children:
            try: ram += child.memory_info().rss
            except psutil.Error: pass
        return {'version':'0.1.0','started':self.started,'detector':self.detector,'detector_error':self.detector_error,'cameras':cameras,'settings':config,'telegram':{'paired':self.telegram.paired(),'username':self.telegram.username,'error':self.telegram.last_error,'last_success':self.telegram.last_success},'memory_mb':round(ram/1024**2),'system_memory_percent':psutil.virtual_memory().percent}

    def status_text(self):
        status = self.status()
        online = sum(c['online'] for c in status['cameras'])
        message = f"Watchyard\nCameras: {online}/4 online\nDetector: {status['detector']}\nAlerts: {'muted' if status['settings']['muted_until']>time.time() or not status['settings']['enabled'] else 'enabled'}\nMemory (service + video processes): {status['memory_mb']} MB"
        if status['detector_error']:
            message += '\nDetection problem: '+status['detector_error']
        return message

    def monitor(self):
        last_cleanup = 0
        while not self.stop.wait(15):
            if time.time()-last_cleanup > 3600:
                self.store.cleanup(self.settings.snapshot()['retention_days'])
                last_cleanup = time.time()
            for camera_id,camera in self.cameras.items():
                online = time.time()-camera.captured_at<12
                previous = self.previous_online.get(camera_id)
                self.previous_online[camera_id] = online
                # Wait through connection startup; one message per transition.
                if time.time()-self.started < 60 or previous is None or previous==online or not self.telegram.paired():
                    continue
                try:
                    name = self.camera_config(camera_id)['name']
                    self.telegram.text(f"{name}: camera {'connection recovered' if online else 'disconnected; reconnecting automatically'}.",disable_notification='true')
                except RuntimeError:
                    pass

    def close(self):
        self.stop.set()
        for camera in self.cameras.values():
            camera.close()
