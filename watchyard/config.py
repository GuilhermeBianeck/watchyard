import copy
import json
import os
import threading
from pathlib import Path

from .runtime import data_directory
from .sources import validate_inventory, validate_urls

DATA = data_directory()
DEFAULTS = {
    "enabled": True,
    "muted_until": 0,
    "retention_days": 7,
    "inference_fps": 1,
    "confidence": 0.55,
    "confirmation_frames": 3,
    "cameras": [
        {"id": 1, "name": "Camera 1", "enabled": True, "zone": [], "labels": ["person", "car", "dog", "cat"]},
        {"id": 2, "name": "Camera 2", "enabled": True, "zone": [], "labels": ["person", "car", "dog", "cat"]},
        {"id": 3, "name": "Camera 3", "enabled": True, "zone": [], "labels": ["person", "car", "dog", "cat"]},
        {"id": 4, "name": "Camera 4", "enabled": True, "zone": [], "labels": ["person", "car", "dog", "cat"]},
    ],
}


class Settings:
    def __init__(self, path=DATA):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.path.chmod(0o700)
        (self.path / "events").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.value = copy.deepcopy(DEFAULTS)
        f = self.path / "settings.json"
        if f.exists():
            self.value.update(json.loads(f.read_text()))
        validate_inventory(self.value["cameras"])
        from .policy import MODES,DEFAULT_SCHEDULE
        for camera in self.value['cameras']:
            camera.setdefault('alert_modes',copy.deepcopy(MODES))
            camera.setdefault('schedule',copy.deepcopy(DEFAULT_SCHEDULE))
        sf = self.path / "secrets.json"
        self.secrets = json.loads(sf.read_text()) if sf.exists() else {}

        validate_urls(self.secrets.get("CAMERA_RTSP_URLS", {}))

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.value)

    def save(self, update):
        with self.lock:
            self.value.update(update)
            self._write("settings.json", self.value)

    def secret(self, key, default=None):
        with self.lock:
            return self.secrets.get(key, default)

    def save_secrets(self, update):
        with self.lock:
            self.secrets.update(update)
            self._write("secrets.json", self.secrets)

    def _write(self, name, data):
        # Restrict permissions before writing sensitive bytes; atomically replace.
        tmp = self.path / (name + ".tmp")
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path / name)
