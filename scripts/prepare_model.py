"""Download official YOLO weights and export locally; no camera images uploaded."""
import os
from pathlib import Path

data = Path(os.environ.get('WATCHYARD_DATA',str(Path.home()/'Library/Application Support/Watchyard')))
models = data/'models'
models.mkdir(parents=True,exist_ok=True)
os.environ['YOLO_CONFIG_DIR'] = str(data/'ultralytics')
os.environ['YOLO_AUTOINSTALL'] = 'false'
os.chdir(models)
from ultralytics import YOLO

if not (models/'yolo11n.mlpackage').exists():
    YOLO('yolo11n.pt').export(format='coreml',imgsz=640,nms=True)
print('Core ML model ready:',models/'yolo11n.mlpackage')
