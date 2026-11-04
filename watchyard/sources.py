"""Map stable Watchyard IDs to private RTSP inputs and optional recorder tracks."""
from urllib.parse import quote, urlsplit


def validate_review_zone(zone):
    if not isinstance(zone, list) or zone and not 3 <= len(zone) <= 20:
        raise ValueError('A review area needs 3 to 20 boundary points, or no points to clear it')
    if any(not isinstance(point, list) or len(point) != 2 or
           any(type(value) not in (int, float) or not 0 <= value <= 1 for value in point)
           for point in zone):
        raise ValueError('Invalid review area coordinates')
    if zone:
        area = sum(x * y2 - x2 * y for (x, y), (x2, y2) in zip(zone, zone[1:] + zone[:1]))
        if abs(area) < 0.0001:
            raise ValueError('Draw a review area with a visible boundary')


def validate_inventory(cameras):
    if not isinstance(cameras, list) or not cameras or len(cameras) > 16:
        raise ValueError('Configure between 1 and 16 cameras')
    seen = set()
    for camera in cameras:
        if not isinstance(camera, dict) or set(camera) - {
            'id', 'name', 'enabled', 'zone', 'labels', 'alert_modes', 'schedule', 'channel', 'replay_track',
            'ignore_boxes', 'shared_ingest', 'plate_zone', 'expected_zone', 'restricted_zone'
        }:
            raise ValueError('Unknown camera fields; keep stream URLs in secrets.json')
        camera_id = camera.get('id')
        if type(camera_id) is not int or camera_id < 1 or camera_id in seen:
            raise ValueError('Camera IDs must be unique positive integers')
        seen.add(camera_id)
        if not isinstance(camera.get('name'), str) or not camera['name'].strip():
            raise ValueError('Each camera needs a name')
        for key in ('channel', 'replay_track'):
            value = camera.get(key)
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError(f'{key} must be a positive integer')
        if type(camera.get('shared_ingest', False)) is not bool:
            raise ValueError('shared_ingest must be true or false')
        if 'plate_zone' in camera:
            rect = camera['plate_zone']
            if (not isinstance(rect, list) or len(rect) != 4
                    or any(type(v) not in (int, float) or not 0 <= v <= 1 for v in rect)
                    or rect[0] >= rect[2] or rect[1] >= rect[3]):
                raise ValueError('Plate zones need four ordered coordinates between 0 and 1')
        for key in ('expected_zone', 'restricted_zone'):
            if key in camera:
                validate_review_zone(camera[key])
        ignored = camera.get('ignore_boxes', {})
        if not isinstance(ignored, dict):
            raise ValueError('ignore_boxes must map object labels to lists of rectangles')
        for label, boxes in ignored.items():
            if label not in ('person', 'car', 'dog', 'cat') or not isinstance(boxes, list):
                raise ValueError('Invalid ignore_boxes label or rectangle list')
            for box in boxes:
                if (not isinstance(box, list) or len(box) != 4
                        or any(type(v) not in (int, float) or not 0 <= v <= 1 for v in box)
                        or box[0] >= box[2] or box[1] >= box[3]):
                    raise ValueError('Ignore boxes need four ordered coordinates between 0 and 1')
        camera.setdefault('enabled', True)
        camera.setdefault('zone', [])
        camera.setdefault('labels', ['person', 'car', 'dog', 'cat'])


def validate_urls(urls):
    if not isinstance(urls, dict):
        raise ValueError('CAMERA_RTSP_URLS must be a map of camera IDs to RTSP URLs')
    for value in urls.values():
        try:
            url = urlsplit(value)
            valid = url.scheme in ('rtsp', 'rtsps') and url.hostname and not url.fragment
        except (TypeError, ValueError, AttributeError):
            valid = False
        if not valid:
            raise ValueError('Camera stream must be an RTSP or RTSPS URL')


class CameraSources:
    def __init__(self, settings):
        self.settings = settings

    def camera(self, camera_id):
        return next((c for c in self.settings.snapshot()['cameras'] if c['id'] == camera_id), None)

    def override(self, camera_id):
        return self.settings.secret('CAMERA_RTSP_URLS', {}).get(str(camera_id))

    def stream(self, camera_id):
        if url := self.override(camera_id):
            return url
        camera = self.camera(camera_id)
        channel = camera.get('channel') or camera_id
        return f'{self.recorder_base()}/Streaming/Channels/{channel}02'

    def recorder_base(self):
        s = self.settings
        user = quote(s.secret('NVR_USERNAME', 'admin'), safe='')
        password = quote(s.secret('NVR_PASSWORD', ''), safe='')
        return f"rtsp://{user}:{password}@{s.secret('NVR_HOST', '127.0.0.1')}:554"

    def track(self, camera_id):
        camera = self.camera(camera_id)
        if camera is None:
            return None
        if 'replay_track' in camera:
            return camera['replay_track']
        if not self.override(camera_id):
            return (camera.get('channel') or camera_id)*100+1
        return None
