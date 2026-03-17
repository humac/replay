FROM nvidia/cuda:12.2.2-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REPLAY_PORT=8090 \
    REPLAY_DATA_DIR=/data \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=video,compute,utility

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 python3-pip ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data /tmp/ffmpeg \
    && chown -R appuser:appuser /app /data /tmp/ffmpeg

USER appuser

EXPOSE 8090

CMD ["python3", "server.py"]
