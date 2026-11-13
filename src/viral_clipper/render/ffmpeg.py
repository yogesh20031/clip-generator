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


def segment_inputs(src: Path, parts: list[tuple[float, float]]) -> list[str]:
    """One accurately-seeked input per segment, so every segment's timestamps start at 0."""
    args: list[str] = []
    for a, b in parts:
        args += ["-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(src)]
    return args


def audio_concat_filter(n: int, durations: list[float], fade_s: float = 0.015) -> str:
    """Trim each segment's audio to its exact length, fade the edges (no clicks at jump cuts), concat."""
    chains = []
    for i, dur in enumerate(durations):
        fade = min(fade_s, dur / 4)
        chains.append(
            f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,apad,atrim=duration={dur:.4f},"
            f"asetpts=PTS-STARTPTS,afade=t=in:d={fade:.3f},afade=t=out:st={max(0.0, dur - fade):.4f}:d={fade:.3f}[a{i}]"
        )
    if n == 1:
        return chains[0].replace("[a0]", "[acat]")
    chains.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[acat]")
    return ";".join(chains)


def measure_loudness(
    src: Path, parts: list[tuple[float, float]], durations: list[float], clip_cfg: ClipConfig
) -> dict[str, str] | None:
    """loudnorm pass 1 over the joined segments. None if the audio is silent or unmeasurable."""
    cmd = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-y",
        *segment_inputs(src, parts),
        "-filter_complex",
        audio_concat_filter(len(parts), durations)
        + f";[acat]loudnorm=I={clip_cfg.loudness_i}:TP={clip_cfg.loudness_tp}:LRA={clip_cfg.loudness_lra}"
        ":print_format=json[aout]",
        "-map",
        "[aout]",
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
