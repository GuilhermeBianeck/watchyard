"""Compare one camera's separate and shared FFmpeg inputs on the same host."""
import argparse
from pathlib import Path
import shutil
from statistics import median
import subprocess
import tempfile
import threading
import time

import psutil

from watchyard.capture import Camera
from watchyard.config import Settings
from watchyard.live import LiveFeed

FRAME_BYTES = Camera.WIDTH * Camera.HEIGHT * 3


def commands(settings, camera_id, directory, fps):
    live = LiveFeed(camera_id, Settings(directory))
    live.settings = settings
    live.generation = 'a' * 12
    live_command = live.command()
    input_end = live_command.index('-i') + 2
    input_args = live_command[:input_end]
    analysis_filter = f'fps={fps},scale={Camera.WIDTH}:{Camera.HEIGHT}'
    raw_output = ['-an', '-sn', '-pix_fmt', 'bgr24', '-f', 'rawvideo', 'pipe:1']
    analysis = input_args + ['-vf', analysis_filter] + raw_output
    return live.directory, {'separate': [analysis, live_command], 'shared': [live.command(fps)]}


def measure(cmds, directory, duration):
    procs = []
    reader = None
    started = time.monotonic()
    frames = 0

    def drain():
        nonlocal frames
        while len(procs[0].stdout.read(FRAME_BYTES)) == FRAME_BYTES:
            frames += 1

    try:
        for index, cmd in enumerate(cmds):
            procs.append(subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                          stdout=subprocess.PIPE if index == 0 else subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL))
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        playlist = directory / 'index.m3u8'
        while not playlist.is_file() or frames == 0:
            if any(proc.poll() is not None for proc in procs) or time.monotonic() - started > 15:
                raise RuntimeError('Camera or encoder did not start')
            time.sleep(.05)
        outputs_ready = time.monotonic() - started
        workers = [psutil.Process(proc.pid) for proc in procs]
        def cpu():
            return sum(sum(worker.cpu_times()[:2]) for worker in workers)

        t0, cpu0, frames0 = time.monotonic(), cpu(), frames
        memory = []
        for _ in range(duration):
            if any(proc.poll() is not None for proc in procs):
                raise RuntimeError('FFmpeg exited during measurement')
            memory.append(sum(worker.memory_info().rss for worker in workers) / 1024**2)
            time.sleep(1)
        elapsed = time.monotonic() - t0
        return (100 * (cpu() - cpu0) / elapsed, median(memory),
                (frames - frames0) / elapsed, outputs_ready)
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if reader:
            reader.join(timeout=3)
        if procs and procs[0].stdout:
            procs[0].stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('camera', type=int, help='Camera ID from the local inventory')
    parser.add_argument('--seconds', type=int, default=20)
    parser.add_argument('--reverse', action='store_true', help='Run shared ingest first')
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error('--seconds must be positive')
    if not shutil.which('ffmpeg'):
        parser.error('ffmpeg is required')
    settings = Settings()
    config = settings.snapshot()
    if args.camera not in {camera['id'] for camera in config['cameras']}:
        parser.error('Unknown camera ID')
    with tempfile.TemporaryDirectory(prefix='watchyard-ingest-') as temp:
        directory, cases = commands(settings, args.camera, Path(temp), config['inference_fps'])
        order = ('shared', 'separate') if args.reverse else ('separate', 'shared')
        for name in order:
            for path in directory.iterdir():
                path.unlink()
            try:
                cpu, rss, fps, startup = measure(cases[name], directory, args.seconds)
            except (OSError, RuntimeError, psutil.Error) as exc:
                parser.exit(1, f'{name}: benchmark failed ({type(exc).__name__})\n')
            print(f'{name}: {cpu:.1f}% of one core, {rss:.1f} MiB RSS, '
                  f'{fps:.2f} analysis fps, {startup:.2f}s until both outputs are ready', flush=True)


if __name__ == '__main__':
    main()
