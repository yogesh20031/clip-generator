"""Visual motion intensity + motion centroid from downscaled grayscale frames.

Frames come from an FFmpeg pipe (fps-filtered, scaled, gray) rather than cv2.VideoCapture so
long videos decode once at the sampling rate and the analysis works on any container.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import numpy as np

from viral_clipper.errors import AnalysisError
from viral_clipper.ingest.ffprobe import ffmpeg_path
from viral_clipper.models import SignalCurve

log = logging.getLogger(__name__)

# Fixed analysis raster. Aspect distortion is irrelevant for diff magnitude and the centroid
# is reported in normalized coordinates anyway.
_W, _H = 160, 90


def iter_gray_frames(video_path: str | Path, fps: float, start: float | None = None, duration: float | None = None):
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(video_path)]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += [
        "-vf",
        f"fps={fps},scale={_W}:{_H},format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    frame_bytes = _W * _H
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(_H, _W)
    finally:
        proc.stdout.close()
        stderr = proc.stderr.read().decode(errors="ignore") if proc.stderr else ""
        code = proc.wait()
        if code not in (0, None) and "Output file is empty" not in stderr:
            log.warning("ffmpeg frame pipe exited %s: %s", code, stderr.strip()[:200])


def analyze_motion(
    video_path: str | Path, duration: float, rate_hz: float
) -> tuple[SignalCurve, list[tuple[float, float]]]:
    n_out = max(1, int(np.ceil(duration * rate_hz)))
    motion = np.zeros(n_out, dtype=np.float32)
    centroids: list[tuple[float, float]] = []
    prev: np.ndarray | None = None
    ys, xs = np.mgrid[0:_H, 0:_W]
    count = 0
    for i, frame in enumerate(iter_gray_frames(video_path, rate_hz)):
        if i >= n_out:
            break
        count += 1
        if prev is None:
            centroids.append((0.5, 0.5))
            prev = frame
            continue
        diff = np.abs(frame.astype(np.int16) - prev.astype(np.int16)).astype(np.float32)
        motion[i] = float(diff.mean())
        mask = diff > 25  # ignore sensor/compression noise
        weight = mask.sum()
        if weight > 0.002 * mask.size:
            cx = float((xs * mask).sum() / weight) / _W
            cy = float((ys * mask).sum() / weight) / _H
            centroids.append((cx, cy))
        else:
            centroids.append(centroids[-1] if centroids else (0.5, 0.5))
        prev = frame
    if count == 0:
        raise AnalysisError("FFmpeg produced no video frames; is the file a valid video?")
    while len(centroids) < n_out:
        centroids.append(centroids[-1] if centroids else (0.5, 0.5))
    log.info("motion: %d frames sampled at %.1f Hz", count, rate_hz)
    return SignalCurve(name="motion", rate_hz=rate_hz, values=motion.tolist()), centroids
