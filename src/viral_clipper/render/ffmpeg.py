"""FFmpeg helpers: running with progress, two-pass loudness measurement, thumbnails."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
from pathlib import Path

from viral_clipper.config import ClipConfig
from viral_clipper.errors import RenderError
from viral_clipper.ingest.ffprobe import ffmpeg_path
from viral_clipper.progress import ProgressFn

log = logging.getLogger(__name__)

_TIME_RE = re.compile(r"out_time_(?:us|ms)=(\d+)")
_JSON_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


def run_ffmpeg(args: list[str], duration: float, progress: ProgressFn | None = None, what: str = "ffmpeg") -> None:
    """Run ffmpeg with machine-readable progress on stdout; raise RenderError with stderr on failure."""
    cmd = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-nostats",
        "-progress",
        "pipe:1",
        *args,
    ]
    log.debug("%s: %s", what, " ".join(cmd))
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout is not None and proc.stderr is not None
    # Drain stderr on a thread: if ffmpeg fills that pipe while we wait on stdout, both sides hang.
    stderr_chunks: list[str] = []
    drain = threading.Thread(target=lambda: stderr_chunks.append(proc.stderr.read()), daemon=True)  # type: ignore[union-attr]
    drain.start()
    last = -1.0
    for line in proc.stdout:
        m = _TIME_RE.search(line)
        if m and progress is not None and duration > 0:
            # out_time_us is microseconds in ffmpeg >= 5, out_time_ms was (confusingly) also µs.
            frac = min(1.0, int(m.group(1)) / 1_000_000 / duration)
            if frac - last >= 0.02:
                last = frac
                progress(frac, f"{what} {frac * 100:.0f}%")
    code = proc.wait()
    drain.join(timeout=5)
    stderr = "".join(stderr_chunks)
    if code != 0:
        log.error("%s failed (%s):\n%s\nstderr:\n%s", what, code, " ".join(cmd), stderr)
        raise RenderError(
            f"{what} failed: {stderr.strip().splitlines()[-1][:300] if stderr.strip() else 'unknown error'}"
        )


def measure_loudness(src: Path, start: float, end: float, clip_cfg: ClipConfig) -> dict[str, str] | None:
    """loudnorm pass 1. Returns the measured values or None if the segment has no usable audio."""
    cmd = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-i",
        str(src),
        "-vn",
        "-af",
        f"loudnorm=I={clip_cfg.loudness_i}:TP={clip_cfg.loudness_tp}:LRA={clip_cfg.loudness_lra}:print_format=json",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    match = _JSON_RE.findall(result.stderr)
    if result.returncode != 0 or not match:
        log.warning("loudnorm measurement failed; falling back to single-pass: %s", result.stderr.strip()[-200:])
        return None
    data = json.loads(match[-1])
    if any(data.get(k) in (None, "-inf", "inf") for k in ("input_i", "input_tp", "input_lra", "input_thresh")):
        return None
    return {k: str(v) for k, v in data.items()}


def loudnorm_filter(measured: dict[str, str] | None, clip_cfg: ClipConfig) -> str:
    base = f"loudnorm=I={clip_cfg.loudness_i}:TP={clip_cfg.loudness_tp}:LRA={clip_cfg.loudness_lra}"
    if measured is None:
        return base
    return (
        f"{base}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured.get('target_offset', '0')}:linear=true:print_format=summary"
    )


def write_thumbnail(clip_path: Path, at: float, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{max(0.0, at):.3f}",
        "-i",
        str(clip_path),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode != 0 or not dest.exists():
        # The peak may sit past the last decodable frame; grab the first frame instead.
        cmd[cmd.index("-ss") + 1] = "0"
        subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return dest


def measure_integrated_loudness(path: Path) -> float | None:
    """ebur128 integrated loudness of a finished file (used by tests and the demo report)."""
    cmd = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-i",
        str(path),
        "-af",
        "ebur128=framelog=quiet",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    m = re.search(r"I:\s*(-?[\d.]+)\s*LUFS", result.stderr)
    return float(m.group(1)) if m else None
