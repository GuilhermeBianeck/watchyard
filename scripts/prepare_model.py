"""Download official YOLO weights and export locally; no camera images uploaded."""
import os
from pathlib import Path

from watchyard.runtime import data_directory
data = data_directory()
models = data/'models'
models.mkdir(parents=True,exist_ok=True)
os.environ['YOLO_CONFIG_DIR'] = str(data/'ultralytics')
os.environ['YOLO_AUTOINSTALL'] = 'false'
os.chdir(models)
from ultralytics import YOLO

from watchyard.runtime import Runtime
runtime = Runtime.read()
target = runtime.model_path(data)
if runtime.backend=='coreml':
    if not target.exists():
        if target != models/'yolo11n.mlpackage':
            raise SystemExit('Provide the custom Core ML model at WATCHYARD_MODEL_PATH.')
        YOLO('yolo11n.pt').export(format='coreml',imgsz=640,nms=True)
else:
    if not target.exists():
        if target != models/'yolo11n.pt':
            raise SystemExit('Provide the custom PyTorch model at WATCHYARD_MODEL_PATH.')
        YOLO('yolo11n.pt')
print('Detector model ready:',target)
