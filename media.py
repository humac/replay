"""Media pipeline — probing, transcoding, and HLS generation."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from collections import deque
from pathlib import Path

import log as _log

logger = _log.setup("replay")


# ---------------------------------------------------------------------------
# Hardware acceleration selection
# ---------------------------------------------------------------------------

# Path probed to detect an Intel iGPU render node. Overridable for tests.
VAAPI_RENDER_NODE = "/dev/dri/renderD128"

# Valid REPLAY_HWACCEL choices, in preference order when "auto" is selected.
# `qsv` and `vaapi` both target the Intel render node but use different
# ffmpeg pipelines — QSV is faster and lower-CPU on Iris Xe / Arc but
# requires the iHD driver; VAAPI works more broadly.
HWACCEL_CHOICES = ("auto", "qsv", "vaapi", "nvenc", "cpu")


def select_hwaccel(preference: str | None = None) -> str:
    """Pick the hardware encoder to attempt before falling back to CPU.

    Returns one of "qsv", "nvenc", "vaapi", "cpu". When *preference* is
    provided (typically the live setting value), it overrides the env var.
    """
    raw = preference if preference is not None else os.environ.get("REPLAY_HWACCEL", "auto")
    choice = (raw or "auto").strip().lower()
    if choice in ("qsv", "nvenc", "vaapi", "cpu"):
        return choice
    # auto: prefer the Intel render node when present (covers the typical
    # Terramaster / NUC / mini-PC deployment); fall back to NVENC otherwise.
    return "qsv" if Path(VAAPI_RENDER_NODE).exists() else "nvenc"

# ---------------------------------------------------------------------------
# Transcode progress tracking
# ---------------------------------------------------------------------------

# Key: "match_id/slot", value: {pct, started_at, updated_at, stage}
_transcode_progress: dict[str, dict] = {}

# Active ffmpeg subprocesses — populated by run_ffmpeg so cancel_active_transcodes
# can terminate them on SIGTERM before asyncio task cancellation gets there.
_active_procs: set = set()


# Limit simultaneous HLS variant ffmpeg processes. TRANSCODE_CONCURRENCY=2 allows
# 2 concurrent transcodes; without this cap each spawns 3+ variants in parallel,
# easily reaching 6+ simultaneous ffmpegs on a 2-core host.
_hls_semaphore = asyncio.Semaphore(2)

# GPU health counters — session-lifetime totals across all encode attempts.
# Mutated via dict to avoid `global` declarations in nested functions.
# Exposed via get_gpu_health() for the admin diagnostics endpoint.
_gpu_stats: dict[str, int] = {"succeeded": 0, "failed": 0}

# Recent transcode results — used by the Performance Tuning panel to compute
# realtime-factor (wall_seconds / source_seconds). Newest entries last.
_transcode_history: deque = deque(maxlen=50)


def get_gpu_health() -> dict:
    """Return a snapshot of GPU encode attempt counters since last restart."""
    return dict(_gpu_stats)


def record_transcode_history(*, match_id: str, slot: str, hwaccel: str,
                             source_seconds: float | None, wall_seconds: float,
                             variant_count: int = 0, kind: str = "transcode") -> None:
    """Append a result to the rolling transcode history. Cheap; safe to call
    from any thread (deque ops are atomic enough for our usage)."""
    _transcode_history.append({
        "match_id": match_id,
        "slot": slot,
        "hwaccel": hwaccel,
        "source_seconds": source_seconds,
        "wall_seconds": round(wall_seconds, 2),
        "variant_count": variant_count,
        "kind": kind,
        "ended_at": time.time(),
        "rt_factor": (round(wall_seconds / source_seconds, 3)
                      if source_seconds and source_seconds > 0 else None),
    })


def get_transcode_history() -> list[dict]:
    return list(_transcode_history)


def get_transcode_progress(match_id: str, slot: str) -> dict | None:
    """Return current progress for a transcode job, or None."""
    return _transcode_progress.get(f"{match_id}/{slot}")


def clear_transcode_progress(match_id: str, slot: str):
    _transcode_progress.pop(f"{match_id}/{slot}", None)


def get_all_transcode_progress() -> dict[str, dict]:
    """Return a snapshot of all active transcode progress entries."""
    return dict(_transcode_progress)


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


async def cancel_active_transcodes():
    """Terminate all in-flight ffmpeg subprocesses and wait for them to exit.

    Called from the lifespan shutdown hook so SIGTERM doesn't leave half-written
    MP4 files on disk that the startup orphan sweep would have to clean up.
    """
    procs = list(_active_procs)
    if not procs:
        return
    logger.info("Shutdown: terminating %d active ffmpeg process(es)", len(procs))
    for proc in procs:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
    await asyncio.gather(*[proc.wait() for proc in procs], return_exceptions=True)


# ---------------------------------------------------------------------------
# Path helpers
#
# The replay app keeps two trees on disk:
#   - `videos_dir` (always the SSD pool): hot path. HLS variants + segments
#     for every match plus per-match thumbnails. Many small random reads on
#     every viewer hit, so it lives on fast storage.
#   - `originals_dir` (configurable via REPLAY_ORIGINALS_DIR; defaults to
#     `videos_dir`): cold path. Raw uploads (`<slot>_raw.{mp4,mkv}`) and
#     finished, transcoded MP4s (`<slot>.mp4`). Large, written once, read
#     rarely — ideal for an HDD pool. Setting `originals_dir` to a separate
#     bind mount lets the SSD hold many more "hot" matches without filling
#     up. When unset, both trees collide and the layout matches the
#     pre-tiering behavior (everything on one volume).
# ---------------------------------------------------------------------------

def slot_hls_dir(videos_dir: Path, match_id: str, slot: str) -> Path:
    return videos_dir / match_id / "hls" / slot


def slot_hls_master_path(videos_dir: Path, match_id: str, slot: str) -> Path:
    return slot_hls_dir(videos_dir, match_id, slot) / "master.m3u8"


def match_originals_dir(originals_dir: Path, match_id: str) -> Path:
    """Per-match cold storage: raw uploads + finished MP4."""
    return originals_dir / match_id


def slot_mp4_path(originals_dir: Path, match_id: str, slot: str) -> Path:
    """Finished, transcoded MP4 for a slot."""
    return match_originals_dir(originals_dir, match_id) / f"{slot}.mp4"


def slot_raw_path(originals_dir: Path, match_id: str, slot: str, ext: str) -> Path:
    """Raw upload destination for a slot (before transcode). `ext` includes
    the leading dot, e.g. '.mp4' or '.mkv'."""
    return match_originals_dir(originals_dir, match_id) / f"{slot}_raw{ext}"


def find_slot_raw_path(originals_dir: Path, match_id: str, slot: str) -> Path | None:
    """Return the existing raw upload file for *slot*, trying .mp4 then .mkv."""
    for ext in (".mp4", ".mkv"):
        p = slot_raw_path(originals_dir, match_id, slot, ext)
        if p.is_file():
            return p
    return None


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
        _active_procs.add(proc)
        try:
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
        finally:
            _active_procs.discard(proc)

    # Simple mode — no progress tracking
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _active_procs.add(proc)
    try:
        _, stderr = await proc.communicate()
        tail = stderr[-500:].decode(errors="replace") if stderr else ""
        return proc.returncode == 0, tail
    finally:
        _active_procs.discard(proc)


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
    hwaccel_preference: str | None = None,
) -> bool:
    width, height = await probe_video_dimensions(source_mp4)
    variants = build_hls_variants(width, height, hls_variant_presets)
    hls_dir = slot_hls_dir(videos_dir, match_id, slot)
    shutil.rmtree(hls_dir, ignore_errors=True)
    hls_dir.mkdir(parents=True, exist_ok=True)

    hwaccel = select_hwaccel(hwaccel_preference)

    def _cpu_cmd(variant: dict, segment_pattern: Path, playlist_path: Path) -> list[str]:
        return [
            "ffmpeg", "-y",
            "-i", str(source_mp4),
            "-vf", f"scale=-2:{variant['height']}",
            "-c:v", "libx264",
            # `fast` preset for the HLS-variant CPU fallback. The fallback
            # only runs if VAAPI fails — when it does, we want it to finish
            # quickly. Quality difference vs `medium` at HLS bitrates is
            # negligible (CRF 20 still bounds quality regardless of preset).
            "-preset", "fast",
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
        ]

    def _qsv_cmd(variant: dict, segment_pattern: Path, playlist_path: Path) -> list[str]:
        # QSV pipeline on the Intel iGPU (i5-1235U Iris Xe and similar). QSV
        # bypasses VAAPI's `low_power` quirks and gives ~30-50% higher real-time
        # factor. `scale_qsv` does the rescale on-GPU end-to-end (unlike the
        # VAAPI pipeline which has to round-trip through CPU). `-look_ahead 1`
        # + `-global_quality` produce noticeably better quality than
        # `h264_vaapi -low_power 1` at the same bitrate.
        return [
            "ffmpeg", "-y",
            "-hwaccel", "qsv",
            "-hwaccel_device", VAAPI_RENDER_NODE,
            "-hwaccel_output_format", "qsv",
            "-i", str(source_mp4),
            "-vf", f"scale_qsv=-1:{variant['height']}",
            "-c:v", "h264_qsv",
            "-preset", "veryslow",
            "-look_ahead", "1",
            "-async_depth", "4",
            "-g", "48",
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
        ]

    def _vaapi_cmd(variant: dict, segment_pattern: Path, playlist_path: Path) -> list[str]:
        # Hybrid VAAPI pipeline: GPU decode → explicit hwdownload → CPU scale
        # → hwupload → GPU encode. scale_vaapi (full GPU rescale) is broken
        # on this iHD driver — fails with "Failed to create processing
        # pipeline context" even though vainfo advertises VAEntrypointVideoProc.
        #
        # `-hwaccel_output_format vaapi` keeps decoded frames as VAAPI surfaces
        # instead of letting ffmpeg auto-convert them to a software pixel
        # format (which can trigger expensive CPU colorspace conversion via
        # the same buggy VPP path). The explicit hwdownload+format=nv12 then
        # does a near-memcpy because nv12 is VAAPI's native surface format,
        # avoiding the unnecessary conversion. The encoder side is unchanged
        # — `hwupload` pushes scaled CPU frames back onto a VAAPI surface
        # for h264_vaapi.
        #
        # Notes:
        #   - `-low_power 1` targets the LP encode entrypoint required by
        #     low-power iGPUs; Iris Xe and up support it natively too.
        #   - h264_vaapi has no -crf / -preset; bitrate control matches the
        #     libx264 VBR settings via -b:v / -maxrate / -bufsize.
        #   - If VAAPI decode silently falls back to software (e.g. an input
        #     codec the iGPU can't decode), this filter chain will fail at
        #     hwdownload — the per-variant CPU fallback in _generate_variant
        #     catches it and runs libx264 instead, so the slot still finishes.
        return [
            "ffmpeg", "-y",
            "-hwaccel", "vaapi",
            "-hwaccel_device", VAAPI_RENDER_NODE,
            "-hwaccel_output_format", "vaapi",
            "-i", str(source_mp4),
            "-vf", f"hwdownload,format=nv12,scale=-2:{variant['height']},format=nv12,hwupload",
            "-c:v", "h264_vaapi", "-low_power", "1",
            "-profile:v", "main",
            "-g", "48",
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
        ]

    async def _try(method: str, cmd: list[str], variant_dir: Path, variant: dict) -> tuple[bool, str]:
        """Run an ffmpeg attempt, recording GPU success/failure stats and
        scrubbing the variant directory on failure so the next method starts
        clean."""
        ok, err = await run_ffmpeg(cmd)
        if method != "cpu":
            stat_key = f"{method}_succeeded" if ok else f"{method}_failed"
            _gpu_stats[stat_key] = _gpu_stats.get(stat_key, 0) + 1
            # Keep the legacy aggregate counters in sync for the existing UI.
            _gpu_stats["succeeded" if ok else "failed"] += 1
        if ok:
            logger.info(
                "HLS variant %s/%s/%s done (%s)", match_id, slot, variant["name"], method,
                extra={"match_id": match_id, "slot": slot, "variant": variant["name"], "hwaccel": method},
            )
        else:
            logger.warning(
                "HLS variant %s/%s/%s %s failed: %s",
                match_id, slot, variant["name"], method, err,
                extra={"match_id": match_id, "slot": slot, "variant": variant["name"], "hwaccel": method},
            )
            shutil.rmtree(variant_dir, ignore_errors=True)
            variant_dir.mkdir(parents=True, exist_ok=True)
        return ok, err

    async def _generate_variant(variant: dict) -> dict | None:
        async with _hls_semaphore:
            variant_dir = hls_dir / variant["name"]
            variant_dir.mkdir(parents=True, exist_ok=True)
            playlist_path = variant_dir / "index.m3u8"
            segment_pattern = variant_dir / "segment_%03d.ts"

            # Build the chain of attempts. Each is a (method, cmd_factory)
            # tuple so we can stop at the first success.
            chain: list[tuple[str, list[str]]] = []
            if hwaccel == "qsv":
                chain.append(("qsv", _qsv_cmd(variant, segment_pattern, playlist_path)))
                chain.append(("vaapi", _vaapi_cmd(variant, segment_pattern, playlist_path)))
            elif hwaccel == "vaapi":
                chain.append(("vaapi", _vaapi_cmd(variant, segment_pattern, playlist_path)))
            # CPU is always the final fallback unless explicitly requested.
            chain.append(("cpu", _cpu_cmd(variant, segment_pattern, playlist_path)))

            last_err = ""
            for method, cmd in chain:
                ok, last_err = await _try(method, cmd, variant_dir, variant)
                if ok:
                    return variant
            logger.warning(
                "HLS variant %s/%s/%s exhausted all methods: %s",
                match_id, slot, variant["name"], last_err,
            )
            return None

    results = await asyncio.gather(*[_generate_variant(v) for v in variants])
    generated_variants = [v for v in results if v is not None]

    # Any variant failure → discard all; an incomplete master.m3u8 would be
    # silently skipped by the backfill check, permanently losing the missing
    # quality level with no signal.
    if len(generated_variants) < len(variants):
        shutil.rmtree(hls_dir, ignore_errors=True)
        return False

    master_lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for variant in generated_variants:
        master_lines.append(
            f"#EXT-X-STREAM-INF:BANDWIDTH={variant['bandwidth']},RESOLUTION={variant['width']}x{variant['height']}"
        )
        master_lines.append(f"{variant['name']}/index.m3u8")

    master_path = slot_hls_master_path(videos_dir, match_id, slot)
    tmp_path = master_path.with_suffix(".m3u8.tmp")
    tmp_path.write_text("\n".join(master_lines) + "\n")
    os.replace(tmp_path, master_path)
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
    transcode_semaphore,
    transcode_concurrency: int,
    set_video_status,
    hwaccel_preference: str | None = None,
):
    """Background task: transcode *src* -> *dest* (H.264 / AAC, faststart).

    Strategy:
      1. If input is already H.264 (+AAC), remux (stream-copy) -- fastest.
      2. Try GPU transcode (NVENC on NVIDIA, VAAPI on Intel iGPU).
      3. Fall back to CPU libx264.

    On failure, *set_video_status* is called with error_info dict containing
    ``error_code``, ``reason``, and ``details`` keys.
    """
    hls_kwargs = dict(
        videos_dir=videos_dir,
        hls_segment_duration=hls_segment_duration,
        hls_variant_presets=hls_variant_presets,
    )
    thumb_path = videos_dir / match_id / "thumb.jpg"

    async def _maybe_generate_thumb(mp4: Path):
        """Generate a match thumbnail if one doesn't exist yet."""
        if not thumb_path.exists():
            await generate_thumbnail(mp4, thumb_path)

    def _on_progress(pct: int):
        _set_transcode_progress(match_id, slot, pct, "transcoding")

    transcode_started_at = time.time()
    try:
        async with transcode_semaphore:
            logger.info("Transcode acquired for %s/%s (max concurrency=%d)", match_id, slot, transcode_concurrency)
            _set_transcode_progress(match_id, slot, 0, "probing")
            v_codec, a_codec = await probe_codecs(src)
            duration_s = await probe_duration(src)
            logger.info("Probe %s/%s: video=%s audio=%s duration=%s", match_id, slot, v_codec, a_codec, duration_s)

            if v_codec is None:
                logger.error("Probe failed for %s/%s — cannot determine codecs", match_id, slot)
                clear_transcode_progress(match_id, slot)
                await set_video_status(match_id, slot, "error", None, error_info={
                    "error_code": "probe_failed",
                    "reason": "Could not determine video codecs",
                    "details": f"ffprobe returned no video codec for {src.name}",
                })
                src.unlink(missing_ok=True)
                return

            shutil.rmtree(slot_hls_dir(videos_dir, match_id, slot), ignore_errors=True)
            dest.unlink(missing_ok=True)

            # --- 1. Remux if already browser-friendly ---
            remux_err = ""
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
                    await _maybe_generate_thumb(dest)
                    clear_transcode_progress(match_id, slot)
                    await set_video_status(match_id, slot, "ready", dest.name)
                    record_transcode_history(
                        match_id=match_id, slot=slot, hwaccel="remux",
                        source_seconds=duration_s,
                        wall_seconds=time.time() - transcode_started_at,
                        kind="remux",
                    )
                    logger.info("Remux done: %s/%s (hls=%s)", match_id, slot, hls_ok)
                    return
                remux_err = err
                logger.warning("Remux failed, will transcode: %s", err)

            # --- 2. GPU transcode (QSV → VAAPI → NVENC) ---
            hwaccel = select_hwaccel(hwaccel_preference)

            qsv_cmd = [
                "ffmpeg", "-y",
                "-hwaccel", "qsv",
                "-hwaccel_device", VAAPI_RENDER_NODE,
                "-hwaccel_output_format", "qsv",
                "-i", str(src),
                "-c:v", "h264_qsv",
                "-preset", "veryslow",
                "-look_ahead", "1",
                "-async_depth", "4",
                "-global_quality", "21",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(dest),
            ]
            nvenc_cmd = [
                "ffmpeg", "-y",
                "-hwaccel", "cuda",
                "-i", str(src),
                "-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr",
                "-cq", "23", "-b:v", "0",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(dest),
            ]
            # `format=nv12|vaapi,hwupload` covers both GPU-decoded and
            # software-decoded inputs — VAAPI decode silently falls back to
            # CPU for codecs the iGPU can't handle, and the encoder needs
            # frames on the GPU either way. `-low_power 1` targets
            # VAEntrypointEncSliceLP for low-power iGPUs.
            vaapi_cmd = [
                "ffmpeg", "-y",
                "-hwaccel", "vaapi",
                "-hwaccel_device", VAAPI_RENDER_NODE,
                "-hwaccel_output_format", "vaapi",
                "-i", str(src),
                "-vf", "format=nv12|vaapi,hwupload",
                "-c:v", "h264_vaapi", "-low_power", "1", "-qp", "23",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(dest),
            ]

            # Build a chain so a transient QSV failure falls back to VAAPI
            # before reaching CPU. The user's explicit preference picks the
            # head of the chain.
            chain: list[tuple[str, list[str]]] = []
            if hwaccel == "qsv":
                chain.append(("qsv", qsv_cmd))
                chain.append(("vaapi", vaapi_cmd))
            elif hwaccel == "vaapi":
                chain.append(("vaapi", vaapi_cmd))
            elif hwaccel == "nvenc":
                chain.append(("nvenc", nvenc_cmd))
            # "cpu" → empty chain, jump straight to CPU fallback.

            ok = False
            gpu_err = "skipped (hwaccel=cpu)" if not chain else ""
            used_method = ""
            for method, cmd in chain:
                logger.info(
                    "GPU transcode %s/%s (%s)", match_id, slot, method,
                    extra={"match_id": match_id, "slot": slot, "hwaccel": method},
                )
                _set_transcode_progress(match_id, slot, 0, f"transcoding (GPU/{method})")
                ok, gpu_err = await run_ffmpeg(
                    cmd, on_progress=_on_progress, duration_s=duration_s,
                )
                stat_key = f"{method}_succeeded" if ok else f"{method}_failed"
                _gpu_stats[stat_key] = _gpu_stats.get(stat_key, 0) + 1
                _gpu_stats["succeeded" if ok else "failed"] += 1
                if ok:
                    used_method = method
                    break
                logger.warning(
                    "%s transcode failed: %s", method, gpu_err,
                    extra={"match_id": match_id, "slot": slot, "hwaccel": method},
                )
                # Discard partial output before next attempt — ffmpeg may have
                # written a truncated MP4.
                dest.unlink(missing_ok=True)

            if ok:
                src.unlink(missing_ok=True)
                _set_transcode_progress(match_id, slot, 95, "generating HLS")
                hls_ok = await build_hls_assets(dest, match_id, slot, **hls_kwargs)
                await _maybe_generate_thumb(dest)
                clear_transcode_progress(match_id, slot)
                await set_video_status(match_id, slot, "ready", dest.name)
                record_transcode_history(
                    match_id=match_id, slot=slot, hwaccel=used_method,
                    source_seconds=duration_s,
                    wall_seconds=time.time() - transcode_started_at,
                    kind="gpu",
                )
                logger.info(
                    "GPU transcode done: %s/%s (%s, hls=%s)", match_id, slot, used_method, hls_ok,
                    extra={"match_id": match_id, "slot": slot, "hwaccel": used_method, "hls_ok": hls_ok},
                )
                return
            logger.warning(
                "All GPU transcodes failed, falling back to CPU: %s", gpu_err,
                extra={"match_id": match_id, "slot": slot, "hwaccel": hwaccel},
            )

            # --- 3. CPU fallback (libx264) ---
            logger.info("CPU transcode %s/%s", match_id, slot)
            _set_transcode_progress(match_id, slot, 0, "transcoding (CPU)")
            ok, cpu_err = await run_ffmpeg(
                ["ffmpeg", "-y",
                 "-i", str(src),
                 "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                 "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart",
                 str(dest)],
                on_progress=_on_progress, duration_s=duration_s,
            )
            if ok:
                src.unlink(missing_ok=True)
                _set_transcode_progress(match_id, slot, 95, "generating HLS")
                hls_ok = await build_hls_assets(dest, match_id, slot, **hls_kwargs)
                await _maybe_generate_thumb(dest)
                clear_transcode_progress(match_id, slot)
                await set_video_status(match_id, slot, "ready", dest.name)
                record_transcode_history(
                    match_id=match_id, slot=slot, hwaccel="cpu",
                    source_seconds=duration_s,
                    wall_seconds=time.time() - transcode_started_at,
                    kind="cpu",
                )
                logger.info(
                    "CPU transcode done: %s/%s (hls=%s)", match_id, slot, hls_ok,
                    extra={"match_id": match_id, "slot": slot, "hls_ok": hls_ok},
                )
                return

            logger.error(
                "All transcode methods failed %s/%s: %s", match_id, slot, cpu_err,
                extra={"match_id": match_id, "slot": slot},
            )
            clear_transcode_progress(match_id, slot)
            details_parts = []
            if remux_err:
                details_parts.append(f"remux: {remux_err}")
            details_parts.append(f"gpu: {gpu_err}")
            details_parts.append(f"cpu: {cpu_err}")
            await set_video_status(match_id, slot, "error", None, error_info={
                "error_code": "all_methods_failed",
                "reason": "All transcode methods (remux/GPU/CPU) failed",
                "details": " | ".join(details_parts),
            })
            src.unlink(missing_ok=True)

    except Exception as exc:
        logger.exception("Transcode error %s/%s: %s", match_id, slot, exc)
        clear_transcode_progress(match_id, slot)
        await set_video_status(match_id, slot, "error", None, error_info={
            "error_code": "unexpected_error",
            "reason": str(exc),
            "details": "",
        })
        src.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Thumbnail generation
# ---------------------------------------------------------------------------

async def generate_thumbnail(
    src: Path,
    dest: Path,
    *,
    position_pct: float = 0.10,
) -> bool:
    """Extract a single JPEG frame from *src* at *position_pct* of duration.

    Returns True on success, False on failure.
    """
    duration = await probe_duration(src)
    if not duration or duration <= 0:
        seek_s = 2.0
    else:
        seek_s = duration * position_pct

    dest.parent.mkdir(parents=True, exist_ok=True)
    ok, err = await run_ffmpeg([
        "ffmpeg", "-y",
        "-ss", f"{seek_s:.2f}",
        "-i", str(src),
        "-frames:v", "1",
        "-q:v", "3",
        "-vf", "scale='min(640,iw)':-2",
        str(dest),
    ])
    if not ok:
        logger.warning("Thumbnail generation failed for %s: %s", src, err)
        dest.unlink(missing_ok=True)
    return ok


async def backfill_thumbnails(
    *,
    videos_dir: Path,
    originals_dir: Path | None = None,
    load_matches,
) -> dict:
    """Generate thumbnails for matches that have ready videos but no thumb.jpg.

    Thumbnails go on the SSD `videos_dir` (every match-card render hits one).
    Source MP4s live on `originals_dir`; falls back to `videos_dir` for the
    legacy single-volume layout.
    """
    if originals_dir is None:
        originals_dir = videos_dir
    matches = await load_matches()
    generated = 0
    skipped = 0

    for match in matches:
        match_id = match["id"]
        thumb_path = videos_dir / match_id / "thumb.jpg"
        if thumb_path.exists():
            continue

        # Find a ready video slot to extract from
        vs = match.get("video_status", {})
        videos = match.get("videos", {})
        for slot in ("full", "first_half", "second_half"):
            if vs.get(slot) == "ready" and videos.get(slot):
                mp4_path = slot_mp4_path(originals_dir, match_id, slot)
                if mp4_path.is_file():
                    ok = await generate_thumbnail(mp4_path, thumb_path)
                    if ok:
                        generated += 1
                        logger.info("Backfilled thumbnail for %s from %s", match_id, slot)
                    else:
                        skipped += 1
                    break
        else:
            skipped += 1

    return {"generated": generated, "skipped": skipped, "total": len(matches)}


# ---------------------------------------------------------------------------
# Asset integrity verification
# ---------------------------------------------------------------------------

def verify_slot_assets(
    videos_dir: Path,
    match_id: str,
    slot: str,
    originals_dir: Path | None = None,
) -> dict:
    """Check that expected media assets exist for a slot.

    Returns a dict with mp4_exists, mp4_size, hls_complete, missing_variants.

    `videos_dir` holds HLS; `originals_dir` (defaults to `videos_dir`) holds
    the finished MP4. The split lets the SSD pool drop large MP4 files when
    REPLAY_ORIGINALS_DIR is configured.
    """
    if originals_dir is None:
        originals_dir = videos_dir
    mp4_path = slot_mp4_path(originals_dir, match_id, slot)
    mp4_exists = mp4_path.is_file()
    mp4_size = mp4_path.stat().st_size if mp4_exists else 0

    hls_dir = slot_hls_dir(videos_dir, match_id, slot)
    master = slot_hls_master_path(videos_dir, match_id, slot)
    master_exists = master.is_file()

    missing_variants: list[str] = []
    if master_exists:
        for line in master.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                variant_playlist = hls_dir / line
                if not variant_playlist.is_file():
                    missing_variants.append(line)

    return {
        "mp4_exists": mp4_exists,
        "mp4_size": mp4_size,
        "hls_master_exists": master_exists,
        "hls_complete": master_exists and len(missing_variants) == 0,
        "missing_variants": missing_variants,
    }


# ---------------------------------------------------------------------------
# HLS backfill
# ---------------------------------------------------------------------------

async def backfill_hls_for_existing_videos(
    *,
    videos_dir: Path,
    originals_dir: Path | None = None,
    hls_segment_duration: int,
    hls_variant_presets: list[dict],
    hls_backfill_lock: asyncio.Lock,
    load_matches,
    ready_slots_missing_hls,
    startup_delay: float = 5.0,
    inter_item_delay: float = 1.0,
    hwaccel_preference: str | None = None,
) -> dict:
    if hls_backfill_lock.locked():
        return {"started": False, "reason": "already-running", "processed": 0, "generated": 0}
    if originals_dir is None:
        originals_dir = videos_dir

    # Delay at startup so fresh uploads get priority on the transcode semaphore
    if startup_delay > 0:
        await asyncio.sleep(startup_delay)

    hls_kwargs = dict(
        videos_dir=videos_dir,
        hls_segment_duration=hls_segment_duration,
        hls_variant_presets=hls_variant_presets,
        hwaccel_preference=hwaccel_preference,
    )
    async with hls_backfill_lock:
        matches = await load_matches()
        candidates = ready_slots_missing_hls(matches)
        generated = 0

        for match_id, slot in candidates:
            mp4_path = slot_mp4_path(originals_dir, match_id, slot)
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
