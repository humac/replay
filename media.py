"""Media pipeline — probing, transcoding, and HLS generation."""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

import log as _log

logger = _log.setup("replay")

# ---------------------------------------------------------------------------
# Transcode progress tracking
# ---------------------------------------------------------------------------

# Key: "match_id/slot", value: {pct, started_at, updated_at, stage}
_transcode_progress: dict[str, dict] = {}


def get_transcode_progress(match_id: str, slot: str) -> dict | None:
    """Return current progress for a transcode job, or None."""
    return _transcode_progress.get(f"{match_id}/{slot}")


def clear_transcode_progress(match_id: str, slot: str):
    _transcode_progress.pop(f"{match_id}/{slot}", None)


def _set_transcode_progress(match_id: str, slot: str, pct: int, stage: str = "transcoding"):
    key = f"{match_id}/{slot}"
    now = time.time()
    entry = _transcode_progress.get(key)
    if entry:
        entry["pct"] = pct
        entry["updated_at"] = now
        entry["stage"] = stage
    else:
        _transcode_progress[key] = {
            "pct": pct,
            "started_at": now,
            "updated_at": now,
            "stage": stage,
        }


# ---------------------------------------------------------------------------
# HLS path helpers
# ---------------------------------------------------------------------------

def slot_hls_dir(videos_dir: Path, match_id: str, slot: str) -> Path:
    return videos_dir / match_id / "hls" / slot


def slot_hls_master_path(videos_dir: Path, match_id: str, slot: str) -> Path:
    return slot_hls_dir(videos_dir, match_id, slot) / "master.m3u8"


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------

async def probe_codecs(src: Path) -> tuple[str | None, str | None]:
    """Return (video_codec, audio_codec) of *src*."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", str(src),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None, None
        data = json.loads(stdout)
        v_codec = a_codec = None
        for s in data.get("streams", []):
            if s.get("codec_type") == "video" and not v_codec:
                v_codec = s.get("codec_name")
            elif s.get("codec_type") == "audio" and not a_codec:
                a_codec = s.get("codec_name")
        return v_codec, a_codec
    except Exception:
        return None, None


async def probe_video_dimensions(src: Path) -> tuple[int | None, int | None]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", str(src),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None, None
        data = json.loads(stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = stream.get("width")
                height = stream.get("height")
                return int(width) if width else None, int(height) if height else None
        return None, None
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Duration probing
# ---------------------------------------------------------------------------

async def probe_duration(src: Path) -> float | None:
    """Return duration in seconds, or None on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", str(src),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        data = json.loads(stdout)
        dur = data.get("format", {}).get("duration")
        return float(dur) if dur else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# FFmpeg execution
# ---------------------------------------------------------------------------

async def run_ffmpeg(cmd: list[str], *, on_progress=None, duration_s: float | None = None) -> tuple[bool, str]:
    """Run an ffmpeg command; return (success, stderr_tail).

    If *on_progress* is provided, ``-progress pipe:1`` is injected and
    progress percentage is reported via the callback.
    """
    if on_progress and duration_s and duration_s > 0:
        cmd = list(cmd)
        # Insert -progress pipe:1 after "ffmpeg"
        cmd[1:1] = ["-progress", "pipe:1"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stderr_chunks = []

        async def _read_stderr():
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                stderr_chunks.append(line)

        stderr_task = asyncio.create_task(_read_stderr())

        # Parse -progress output from stdout
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").strip()
            if text.startswith("out_time_us="):
                try:
                    us = int(text.split("=", 1)[1])
                    pct = min(99, int((us / 1_000_000) / duration_s * 100))
                    on_progress(pct)
                except (ValueError, ZeroDivisionError):
                    pass

        await stderr_task
        await proc.wait()
        stderr = b"".join(stderr_chunks)
        tail = stderr[-500:].decode(errors="replace") if stderr else ""
        return proc.returncode == 0, tail

    # Simple mode — no progress tracking
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    tail = stderr[-500:].decode(errors="replace") if stderr else ""
    return proc.returncode == 0, tail


# ---------------------------------------------------------------------------
# HLS variant selection & generation
# ---------------------------------------------------------------------------

def build_hls_variants(
    width: int | None,
    height: int | None,
    hls_variant_presets: list[dict],
) -> list[dict]:
    selected = []
    source_height = height or 0
    source_width = width or 0

    for preset in hls_variant_presets:
        if source_height >= preset["height"] or source_width >= preset["width"]:
            selected.append(dict(preset))

    if selected:
        return selected

    fallback_height = max(240, source_height or 480)
    if fallback_height % 2:
        fallback_height -= 1
    return [{
        "name": f"{fallback_height}p",
        "height": fallback_height,
        "width": source_width or 854,
        "video_bitrate": "1400k",
        "maxrate": "1600k",
        "bufsize": "3200k",
        "audio_bitrate": "128k",
        "bandwidth": 1800000,
    }]


async def build_hls_assets(
    source_mp4: Path,
    match_id: str,
    slot: str,
    *,
    videos_dir: Path,
    hls_segment_duration: int,
    hls_variant_presets: list[dict],
) -> bool:
    width, height = await probe_video_dimensions(source_mp4)
    variants = build_hls_variants(width, height, hls_variant_presets)
    hls_dir = slot_hls_dir(videos_dir, match_id, slot)
    shutil.rmtree(hls_dir, ignore_errors=True)
    hls_dir.mkdir(parents=True, exist_ok=True)

    async def _generate_variant(variant: dict) -> dict | None:
        variant_dir = hls_dir / variant["name"]
        variant_dir.mkdir(parents=True, exist_ok=True)
        playlist_path = variant_dir / "index.m3u8"
        segment_pattern = variant_dir / "segment_%03d.ts"

        ok, err = await run_ffmpeg([
            "ffmpeg", "-y",
            "-i", str(source_mp4),
            "-vf", f"scale=-2:{variant['height']}",
            "-c:v", "libx264",
            "-preset", "medium",
            "-profile:v", "main",
            "-crf", "20",
            "-g", "48",
            "-keyint_min", "48",
            "-sc_threshold", "0",
            "-b:v", variant["video_bitrate"],
            "-maxrate", variant["maxrate"],
            "-bufsize", variant["bufsize"],
            "-c:a", "aac",
            "-b:a", variant["audio_bitrate"],
            "-ac", "2",
            "-ar", "48000",
            "-f", "hls",
            "-hls_time", str(hls_segment_duration),
            "-hls_playlist_type", "vod",
            "-hls_flags", "independent_segments",
            "-hls_segment_filename", str(segment_pattern),
            str(playlist_path),
        ])
        if not ok:
            logger.warning("HLS variant generation failed %s/%s/%s: %s", match_id, slot, variant['name'], err)
            return None
        return variant

    results = await asyncio.gather(*[_generate_variant(v) for v in variants])
    generated_variants = [v for v in results if v is not None]

    if not generated_variants:
        shutil.rmtree(hls_dir, ignore_errors=True)
        return False

    master_lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for variant in generated_variants:
        master_lines.append(
            f"#EXT-X-STREAM-INF:BANDWIDTH={variant['bandwidth']},RESOLUTION={variant['width']}x{variant['height']}"
        )
        master_lines.append(f"{variant['name']}/index.m3u8")

    slot_hls_master_path(videos_dir, match_id, slot).write_text("\n".join(master_lines) + "\n")
    return True


# ---------------------------------------------------------------------------
# Transcoding (GPU-first, CPU fallback)
# ---------------------------------------------------------------------------

async def transcode_video(
    match_id: str,
    slot: str,
    src: Path,
    dest: Path,
    *,
    videos_dir: Path,
    hls_segment_duration: int,
    hls_variant_presets: list[dict],
    transcode_semaphore: asyncio.Semaphore,
    transcode_concurrency: int,
    set_video_status,
):
    """Background task: transcode *src* -> *dest* (H.264 / AAC, faststart).

    Strategy:
      1. If input is already H.264 (+AAC), remux (stream-copy) -- fastest.
      2. Try GPU transcode with h264_nvenc.
      3. Fall back to CPU libx264.
    """
    hls_kwargs = dict(
        videos_dir=videos_dir,
        hls_segment_duration=hls_segment_duration,
        hls_variant_presets=hls_variant_presets,
    )

    def _on_progress(pct: int):
        _set_transcode_progress(match_id, slot, pct, "transcoding")

    try:
        async with transcode_semaphore:
            logger.info("Transcode acquired for %s/%s (max concurrency=%d)", match_id, slot, transcode_concurrency)
            _set_transcode_progress(match_id, slot, 0, "probing")
            v_codec, a_codec = await probe_codecs(src)
            duration_s = await probe_duration(src)
            logger.info("Probe %s/%s: video=%s audio=%s duration=%s", match_id, slot, v_codec, a_codec, duration_s)
            shutil.rmtree(slot_hls_dir(videos_dir, match_id, slot), ignore_errors=True)
            dest.unlink(missing_ok=True)

            # --- 1. Remux if already browser-friendly ---
            if v_codec == "h264" and a_codec in ("aac", None):
                logger.info("Remuxing (stream copy) %s/%s", match_id, slot)
                _set_transcode_progress(match_id, slot, 0, "remuxing")
                ok, err = await run_ffmpeg(
                    ["ffmpeg", "-y", "-i", str(src),
                     "-c", "copy", "-movflags", "+faststart",
                     str(dest)],
                    on_progress=_on_progress, duration_s=duration_s,
                )
                if ok:
                    src.unlink(missing_ok=True)
                    _set_transcode_progress(match_id, slot, 95, "generating HLS")
                    hls_ok = await build_hls_assets(dest, match_id, slot, **hls_kwargs)
                    clear_transcode_progress(match_id, slot)
                    await set_video_status(match_id, slot, "ready", dest.name)
                    logger.info("Remux done: %s/%s (hls=%s)", match_id, slot, hls_ok)
                    return
                logger.warning("Remux failed, will transcode: %s", err)

            # --- 2. GPU transcode (NVENC) ---
            logger.info("GPU transcode %s/%s", match_id, slot)
            _set_transcode_progress(match_id, slot, 0, "transcoding (GPU)")
            ok, err = await run_ffmpeg(
                ["ffmpeg", "-y",
                 "-hwaccel", "cuda",
                 "-i", str(src),
                 "-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr",
                 "-cq", "23", "-b:v", "0",
                 "-c:a", "aac", "-b:a", "128k",
                 "-movflags", "+faststart",
                 str(dest)],
                on_progress=_on_progress, duration_s=duration_s,
            )
            if ok:
                src.unlink(missing_ok=True)
                _set_transcode_progress(match_id, slot, 95, "generating HLS")
                hls_ok = await build_hls_assets(dest, match_id, slot, **hls_kwargs)
                clear_transcode_progress(match_id, slot)
                await set_video_status(match_id, slot, "ready", dest.name)
                logger.info("GPU transcode done: %s/%s (hls=%s)", match_id, slot, hls_ok)
                return
            logger.warning("GPU transcode failed, falling back to CPU: %s", err)

            # --- 3. CPU fallback (libx264) ---
            logger.info("CPU transcode %s/%s", match_id, slot)
            _set_transcode_progress(match_id, slot, 0, "transcoding (CPU)")
            ok, err = await run_ffmpeg(
                ["ffmpeg", "-y",
                 "-i", str(src),
                 "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                 "-c:a", "aac", "-b:a", "128k",
                 "-movflags", "+faststart",
                 str(dest)],
                on_progress=_on_progress, duration_s=duration_s,
            )
            if ok:
                src.unlink(missing_ok=True)
                _set_transcode_progress(match_id, slot, 95, "generating HLS")
                hls_ok = await build_hls_assets(dest, match_id, slot, **hls_kwargs)
                clear_transcode_progress(match_id, slot)
                await set_video_status(match_id, slot, "ready", dest.name)
                logger.info("CPU transcode done: %s/%s (hls=%s)", match_id, slot, hls_ok)
                return

            logger.error("All transcode methods failed %s/%s: %s", match_id, slot, err)
            clear_transcode_progress(match_id, slot)
            await set_video_status(match_id, slot, "error", None)
            src.unlink(missing_ok=True)

    except Exception as exc:
        logger.exception("Transcode error %s/%s: %s", match_id, slot, exc)
        clear_transcode_progress(match_id, slot)
        await set_video_status(match_id, slot, "error", None)
        src.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# HLS backfill
# ---------------------------------------------------------------------------

async def backfill_hls_for_existing_videos(
    *,
    videos_dir: Path,
    hls_segment_duration: int,
    hls_variant_presets: list[dict],
    hls_backfill_lock: asyncio.Lock,
    load_matches,
    ready_slots_missing_hls,
    startup_delay: float = 5.0,
    inter_item_delay: float = 1.0,
) -> dict:
    if hls_backfill_lock.locked():
        return {"started": False, "reason": "already-running", "processed": 0, "generated": 0}

    # Delay at startup so fresh uploads get priority on the transcode semaphore
    if startup_delay > 0:
        await asyncio.sleep(startup_delay)

    hls_kwargs = dict(
        videos_dir=videos_dir,
        hls_segment_duration=hls_segment_duration,
        hls_variant_presets=hls_variant_presets,
    )
    async with hls_backfill_lock:
        matches = await load_matches()
        candidates = ready_slots_missing_hls(matches)
        generated = 0

        for match_id, slot in candidates:
            mp4_path = videos_dir / match_id / f"{slot}.mp4"
            try:
                ok = await build_hls_assets(mp4_path, match_id, slot, **hls_kwargs)
                if ok:
                    generated += 1
                    logger.info("Backfilled HLS assets for %s/%s", match_id, slot)
            except Exception:
                logger.exception("Failed to backfill HLS for %s/%s", match_id, slot)
            # Yield between items so new uploads aren't starved
            if inter_item_delay > 0:
                await asyncio.sleep(inter_item_delay)

        return {
            "started": True,
            "processed": len(candidates),
            "generated": generated,
        }
