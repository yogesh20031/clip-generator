"""FFmpeg/ffprobe discovery and media probing."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from viral_clipper.errors import FFmpegMissingError, UnsupportedFormatError

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def ffmpeg_path() -> str:
    return _binary("ffmpeg", "FFMPEG_BINARY")


def ffprobe_path() -> str:
    return _binary("ffprobe", "FFPROBE_BINARY")


@lru_cache(maxsize=4)
def _binary(name: str, env_var: str) -> str:
    override = os.environ.get(env_var)
    if override and Path(override).exists():
        return override
    found = shutil.which(name)
    if not found:
        raise FFmpegMissingError(f"`{name}` was not found on PATH.")
    return found


def ensure_ffmpeg() -> None:
    """Raise FFmpegMissingError early so every tool fails with a clear message."""
    ffmpeg_path()
    ffprobe_path()


@dataclass(frozen=True)
class ProbeInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


def probe(path: str | Path) -> ProbeInfo:
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(f"{path.name} has an unsupported extension.")
    cmd = [
        ffprobe_path(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as exc:
        raise UnsupportedFormatError(f"ffprobe could not read {path.name}: {exc.stderr.strip()[:200]}") from exc
    data = json.loads(out)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise UnsupportedFormatError(f"{path.name} has no video stream.")
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0.0)
    fps = _parse_rate(video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1")
    return ProbeInfo(
        duration=duration,
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        fps=fps,
        has_audio=has_audio,
    )


def _parse_rate(rate: str) -> float:
    try:
        value = float(Fraction(rate))
    except (ValueError, ZeroDivisionError):
        return 30.0
    return value if value > 0 else 30.0
