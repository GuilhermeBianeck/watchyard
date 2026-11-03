import logging
import os
import threading
import time
import uuid

import cv2
import psutil

from . import __version__
from .capture import Camera, draw_detection
from .rules import Tracker, ignored_box
from .store import Store
from .telegram import Telegram
from .notifications import Notifications
from .policy import decision
from .runtime import Runtime
from .replay import Clips
from .live import Live
from .plates import Plates
from .correlation import hint as correlation_hint

log = logging.getLogger('watchyard')


class Service:
    def __init__(self, settings):
        self.settings = settings
        self.runtime = Runtime.read()
        self.stop = threading.Event()
        self.store = Store(settings.path)
        self.plates = Plates(settings, self.store, self.stop)
        self.clips = Clips(settings,self.stop,self.store)
        self.cameras = {i:Camera(i,settings,self.stop) for i in (c['id'] for c in settings.snapshot()['cameras'])}
        self.live = Live(settings,self.stop,self.cameras)
        self.trackers = {i:Tracker() for i in self.cameras}
        self.telegram = Telegram(settings,self)
        self.notifications = Notifications(settings,self.telegram)
        self.started = time.time()
        self.detector = 'loading'
        self.detector_error = None
        self.model = None
        self.previous_online = {}
        self.monitor_thread = None

    def start(self):
        self.clips.start()
        self.plates.start()
        self.live.start()
        for camera in self.cameras.values():
            camera.start()
        self.telegram.start()
        self.notifications.start(self.store,self.stop)
        threading.Thread(target=self.detect,name='detector',daemon=True).start()
        self.monitor_thread = threading.Thread(target=self.monitor,name='health-monitor',daemon=True)
        self.monitor_thread.start()

    def camera_config(self, camera_id):
        return next(c for c in self.settings.snapshot()['cameras'] if c['id']==camera_id)

    def load_model(self):
        os.environ['YOLO_CONFIG_DIR'] = str(self.settings.path/'ultralytics')
        os.environ['YOLO_AUTOINSTALL'] = 'false'
        from ultralytics import YOLO
        model_path = self.runtime.model_path(self.settings.path)
        if not model_path.exists():
            raise RuntimeError('Detector model missing. Run scripts/prepare_model.py for the selected backend.')
        self.model = YOLO(str(model_path), task='detect')
        # Force compile/warm-up now so status never says ready before inference works.
        import numpy as np
        self.model.predict(np.zeros((540,960,3),dtype=np.uint8), verbose=False, imgsz=640, **self.runtime.prediction_options())
        self.detector = 'YOLO11 nano · '+('Core ML' if self.runtime.backend=='coreml' else 'PyTorch '+self.runtime.device)
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
                scheduled = time.monotonic()
                try:
                    self.analyse_frame(camera, c, frame, captured, sequence, config)
                    camera.analysis_error = None
                except Exception as exc:
                    camera.analysis_error = type(exc).__name__
                    log.error('Analysis failed on camera %s: %s', camera.id, camera.analysis_error)
                    # Back off only this camera. Other views keep their normal schedule.
                    next_due[camera.id] = time.monotonic() + 2
                    continue
                next_due[camera.id] = scheduled + 1 / max(0.5, config['inference_fps'])
            self.stop.wait(0.02)

    def analyse_frame(self, camera, camera_config, frame, captured, sequence, config):
        start = time.perf_counter()
        result = self.model.predict(frame, conf=config['confidence'], classes=[0,2,15,16], imgsz=640, verbose=False, **self.runtime.prediction_options())[0]
        h,w = frame.shape[:2]
        detections = []
        for box in result.boxes:
            label = result.names[int(box.cls[0])]
            if label not in camera_config['labels']:
                continue
            coords = box.xyxy[0].cpu().tolist()
            bounds = [max(0, min(1, v / (w if i % 2 == 0 else h)))
                      for i, v in enumerate(coords)]
            if not ignored_box(label, bounds, camera_config):
                detections.append({'label': label, 'confidence': float(box.conf[0]), 'box': bounds})
        camera.publish_detections(detections, sequence)
        camera.analysed_frames += 1
        camera.inference_ms = round((time.perf_counter()-start)*1000,1)
        window=max(3,config['confirmation_frames']/config['inference_fps']+.5)
        tracker = self.trackers[camera_config['id']]
        observed = time.monotonic()
        events = tracker.update(detections,observed,camera_config['zone'],config['confirmation_frames'],window=window)
        self.store.extend_observations(
            [track.event_id for track in tracker.tracks.values()
             if track.event_id and track.last == observed], captured)
        for event in events:
            track = tracker.tracks[event['track_id']]
            first_seen = captured - (observed - track.first)
            track.event_id = self.record(camera_config,frame,event,config,first_seen=first_seen,last_seen=captured)

    def ready(self):
        if self.detector in ('loading', 'unavailable') or self.detector_error:
            return False
        now = time.time()
        for config in self.settings.snapshot()['cameras']:
            if not config['enabled']:
                continue
            camera = self.cameras[config['id']]
            if camera.analysis_error or now - camera.captured_at >= 12 or now - camera.detected_at >= 12:
                return False
        return True

    def record(self, camera, frame, event, config, *, first_seen=None, last_seen=None):
        image = frame.copy()
        draw_detection(image,event)
        name = uuid.uuid4().hex+'.jpg'
        ok = cv2.imwrite(str(self.settings.path/'events'/name),image,[cv2.IMWRITE_JPEG_QUALITY,90])
        if not ok:
            raise RuntimeError('Could not save event snapshot')
        mode,reason = decision(config,camera,event['label'],time.time())
        status = 'pending' if mode!='off' else 'recorded'
        if not config['enabled'] or config['muted_until'] > time.time():
            status = 'muted'
        elif status == 'pending' and not self.notifications.targets():
            status = 'unpaired'
        activity_hint = None
        if event['label'] in ('person', 'car'):
            try:
                activity_hint = correlation_hint(frame, event['box'])
            except (cv2.error, ValueError):
                log.debug('Activity cues unavailable for camera %s', camera['id'])
        event_id = self.store.add(camera,event['label'],event['confidence'],name,status,reason,mode,
                                  first_seen=first_seen,last_seen=last_seen,
                                  correlation_hint=activity_hint)
        if event['label'] == 'car':
            self.plates.submit(camera, event_id)
        log.info('Confirmed %s on camera %s (%s)',event['label'],camera['id'],status)
        return event_id

    def overlays(self):
        return {c['id']: self.cameras[c['id']].display_detections(c)
                for c in self.settings.snapshot()['cameras']}

    def status(self):
        now = time.time()
        config = self.settings.snapshot()
        cameras = []
        for c in config['cameras']:
            camera = self.cameras[c['id']]
            cameras.append({**c,'online':now-camera.captured_at<12,'captured_at':camera.captured_at,'detected_at':camera.detected_at,'inference_ms':camera.inference_ms,'analysis_error':camera.analysis_error,'analysed_frames':camera.analysed_frames,'decoder':camera.mode,'reconnects':camera.reconnects,'error':camera.last_error,'detections':camera.display_detections(c)})
        process = psutil.Process()
        children = process.children(recursive=True)
        ram = process.memory_info().rss
        for child in children:
            try: ram += child.memory_info().rss
            except psutil.Error: pass
        return {'version':__version__,'started':self.started,'detector':self.detector,'detector_error':self.detector_error,'cameras':cameras,'settings':config,'live':self.live.status(),'notifications':self.notifications.status(),'telegram':{'paired':self.telegram.paired(),'accounts':len(self.telegram.members.recipients()),'username':self.telegram.username,'error':self.telegram.last_error,'last_success':self.telegram.last_success,'last_send_at':self.telegram.last_send_at,'delivery_error':self.telegram.last_delivery_error,'poll_error':self.telegram.last_poll_error},'memory_mb':round(ram/1024**2),'system_memory_percent':psutil.virtual_memory().percent}

    def status_text(self):
        status = self.status()
        online = sum(c['online'] for c in status['cameras'])
        message = f"Watchyard\nCameras: {online}/{len(status['cameras'])} online\nDetector: {status['detector']}\nAlerts: {'muted' if status['settings']['muted_until']>time.time() or not status['settings']['enabled'] else 'enabled'}\nMemory (service + video processes): {status['memory_mb']} MB"
        if status['detector_error']:
            message += '\nDetection problem: '+status['detector_error']
        cameras_with_errors = [c['name'] for c in status['cameras'] if c['enabled'] and c['analysis_error']]
        if cameras_with_errors:
            message += '\nAnalysis needs attention: ' + ', '.join(cameras_with_errors)
        return message

    def monitor(self):
        last_cleanup = 0
        last_sample = 0
        while not self.stop.wait(15):
            now = time.time()
            if now-last_cleanup > 3600:
                self.store.cleanup(self.settings.snapshot()['retention_days'])
                self.clips.cleanup()
                last_cleanup = now
            if now-last_sample >= 60:
                self.store.sample(self.status())
                last_sample = now
            if now-self.started < 60:
                continue
            for camera_id,camera in self.cameras.items():
                config = self.camera_config(camera_id)
                healthy = now - camera.captured_at < 30
                if config['enabled'] and self.model is not None:
                    healthy = healthy and not camera.analysis_error and now - camera.detected_at < 45
                self.store.observe_health('camera-'+str(camera_id), config['name'], healthy)

    def close(self):
        self.stop.set()
        self.live.close()
        self.clips.close()
        for camera in self.cameras.values():
            camera.close()
