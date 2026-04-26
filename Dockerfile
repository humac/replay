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
       # sqlite3 CLI for `docker exec replay sqlite3 /data/replay.db ...`
       # debugging without having to drop into python.
       sqlite3 \
       # Intel VAAPI / QSV userspace so the same image can transcode on
       # Intel iGPU hosts. NVIDIA hosts ignore these. iHD covers Gen9+ (most
       # modern Intel CPUs); i965 is kept for older hardware. vainfo is a
       # tiny diagnostic tool — useful for `docker exec replay vainfo`.
       libva-drm2 libva2 intel-media-va-driver i965-va-driver vainfo \
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
