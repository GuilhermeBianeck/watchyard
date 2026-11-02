FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata ffmpeg libglib2.0-0 libgl1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY watchyard ./watchyard
COPY scripts ./scripts
# CPU baseline. GPU/accelerator builds are separate, future deployment choices.
RUN python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install .
RUN useradd --uid 10001 --create-home watchyard
USER 10001:10001
ENV WATCHYARD_DATA=/data WATCHYARD_DEPLOYMENT=vps WATCHYARD_MODEL_BACKEND=pytorch \
    WATCHYARD_MODEL_DEVICE=cpu WATCHYARD_DECODER=software WATCHYARD_LOCAL_BYPASS=0 \
    WATCHYARD_HOST=0.0.0.0 WATCHYARD_PORT=8765 WATCHYARD_PROXY_HEADERS=0 \
    WATCHYARD_WATCHDOG_HEALTH_ONLY=1 YOLO_AUTOINSTALL=false OMP_NUM_THREADS=2 \
    YOLO_CONFIG_DIR=/data/ultralytics MPLCONFIGDIR=/tmp/matplotlib XDG_CACHE_HOME=/tmp/cache
EXPOSE 8765
CMD ["python", "-m", "watchyard.app"]
