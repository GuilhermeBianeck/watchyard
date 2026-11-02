import copy
import json
import os
import threading
from pathlib import Path

DATA = Path(os.environ.get("WATCHYARD_DATA", str(Path.home() / "Library/Application Support/Watchyard")))
DEFAULTS = {
    "enabled": True,
    "muted_until": 0,
    "retention_days": 7,
    "inference_fps": 2,
    "confidence": 0.55,
    "confirmation_frames": 3,
    "cameras": [
        {"id": 1, "name": "Portão", "enabled": True, "zone": [], "labels": ["person", "car", "dog", "cat"]},
        {"id": 2, "name": "Entrada", "enabled": True, "zone": [], "labels": ["person", "car", "dog", "cat"]},
        {"id": 3, "name": "Quartinho", "enabled": True, "zone": [], "labels": ["person", "car", "dog", "cat"]},
        {"id": 4, "name": "Fundos", "enabled": True, "zone": [], "labels": ["person", "car", "dog", "cat"]},
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
        sf = self.path / "secrets.json"
        self.secrets = json.loads(sf.read_text()) if sf.exists() else {}

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
