import time
from types import SimpleNamespace

import numpy as np
from fastapi.testclient import TestClient

from watchyard.app import create_app
from watchyard.config import Settings
from watchyard.service import Service


def test_bad_frame_does_not_stall_other_cameras_and_is_visible_in_readiness(tmp_path, monkeypatch):
    service = Service(Settings(tmp_path))
    service.detector = 'Ready model'
    calls = []
    now = time.time()
    for camera_id, camera in service.cameras.items():
        camera.frame = np.full((12, 12, 3), camera_id, dtype=np.uint8)
        camera.captured_at = now
        camera.sequence = 1

    class Model:
        def predict(self, frame, **kwargs):
            camera_id = int(frame[0, 0, 0])
            calls.append(camera_id)
            if camera_id == 1:
                raise ValueError('Bad frame')
            return [SimpleNamespace(boxes=[])]

    service.model = Model()
    waits = []

    def stop_after_first_pass(seconds):
        waits.append(seconds)
        if seconds == .02:
            service.stop.set()
        return service.stop.is_set()

    monkeypatch.setattr(service.stop, 'wait', stop_after_first_pass)
    service.detect()
    assert calls == [1, 2, 3, 4]
    assert waits == [.02]
    assert service.cameras[1].analysis_error == 'ValueError'
    assert all(service.cameras[i].analysed_frames == 1 for i in (2, 3, 4))

    client = TestClient(create_app(service, run_service=False))
    assert client.get('/healthz').status_code == 503
    assert client.get('/api/status').json()['cameras'][0]['analysis_error'] == 'ValueError'
    service.cameras[1].analysis_error = None
    service.cameras[1].detected_at = time.time()
    assert client.get('/healthz').text == 'ready'
