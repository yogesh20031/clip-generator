"""Smart 9:16 reframing: follow the face, else the motion, else stay centred.

Produces an FFmpeg `crop` x (or y) expression that linearly interpolates between 1 Hz keyframes,
so pans are smooth, with hard jumps at scene cuts.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from viral_clipper.ingest.ffprobe import ffmpeg_path
from viral_clipper.models import AnalysisResult

log = logging.getLogger(__name__)

SAMPLE_HZ = 2.0
DETECT_WIDTH = 320
EMA_ALPHA = 0.35
MAX_PAN_PER_S = 0.25  # fraction of frame width per second, clamps whip-pans


@dataclass(frozen=True)
class CropPlan:
    crop_w: int
    crop_h: int
    axis: str  # "x" (landscape source) or "y" (portrait source)
    keyframes: list[tuple[float, int]]  # (t_rel, offset) at 1 Hz plus cut jumps

    def expression(self) -> str:
        """Piecewise-linear FFmpeg expression in `t` for the tracked axis."""
        if len(self.keyframes) == 1:
            return str(self.keyframes[0][1])
        parts: list[str] = []
        for (t0, v0), (t1, v1) in zip(self.keyframes, self.keyframes[1:], strict=False):
            if t1 - t0 <= 1e-3:
                continue
            # lerp between consecutive keyframes
            parts.append(f"if(lt(t,{t1:.3f}),{v0}+({v1}-{v0})*(t-{t0:.3f})/{t1 - t0:.3f},")
        expr = "".join(parts) + str(self.keyframes[-1][1]) + ")" * len(parts)
        return expr

    def static_offset(self) -> int:
        return self.keyframes[0][1]


def _iter_bgr_frames(video_path: str | Path, start: float, duration: float, width: int, height: int):
    cmd = [
        ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(video_path),
        "-t",
        f"{duration:.3f}",
        "-vf",
        f"fps={SAMPLE_HZ},scale={width}:{height}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    nbytes = width * height * 3
    try:
        while True:
            buf = proc.stdout.read(nbytes)
            if len(buf) < nbytes:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 3)
    finally:
        proc.stdout.close()
        proc.wait()


def _face_centres(
    video_path: str, start: float, duration: float, src_w: int, src_h: int, model_path: Path
) -> list[tuple[float, float] | None]:
    """Normalized centre of the largest face per sample, None where no face was found."""
    try:
        import cv2
    except ImportError:  # pragma: no cover - cv2 is a hard dependency, but keep rendering alive
        return []
    if not model_path.exists():
        log.warning("face model %s missing; using motion-only reframing", model_path)
        return []
    w = DETECT_WIDTH
    h = max(2, int(round(src_h * w / src_w / 2)) * 2)
    detector = cv2.FaceDetectorYN.create(str(model_path), "", (w, h), 0.7, 0.3, 50)
    centres: list[tuple[float, float] | None] = []
    for frame in _iter_bgr_frames(video_path, start, duration, w, h):
        _, faces = detector.detect(frame)
        if faces is None or len(faces) == 0:
            centres.append(None)
            continue
        best = max(faces, key=lambda f: f[2] * f[3])
        x, y, fw, fh = best[:4]
        centres.append(((x + fw / 2) / w, (y + fh / 2) / h))
    return centres


def plan_crop(
    analysis: AnalysisResult,
    start: float,
    end: float,
    out_w: int,
    out_h: int,
    face_model: Path,
) -> CropPlan:
    video = analysis.video
    src_w, src_h = video.width, video.height
    target = out_w / out_h
    if src_w / src_h >= target:
        crop_h = src_h
        crop_w = int(round(src_h * target / 2)) * 2
        axis = "x"
        span = src_w - crop_w
    else:
        crop_w = src_w
        crop_h = int(round(src_w / target / 2)) * 2
        axis = "y"
        span = src_h - crop_h
    duration = end - start
    n = max(1, int(np.ceil(duration * SAMPLE_HZ)))
    if span <= 0:
        return CropPlan(crop_w, crop_h, axis, [(0.0, 0)])

    faces = _face_centres(video.path, start, duration, src_w, src_h, face_model)
    centroids = analysis.motion_centroids
    c_rate = analysis.centroid_rate_hz

    def motion_centre(t_abs: float) -> float | None:
        if not centroids:
            return None
        i = min(len(centroids) - 1, int(t_abs * c_rate))
        cx, cy = centroids[i]
        return cx if axis == "x" else cy

    cuts = [c - start for c in analysis.scene_cuts if start < c < end]
    raw: list[float] = []
    for k in range(n):
        t_rel = k / SAMPLE_HZ
        face = faces[k] if k < len(faces) else None
        if face is not None:
            raw.append(face[0] if axis == "x" else face[1])
        else:
            mc = motion_centre(start + t_rel)
            raw.append(mc if mc is not None else 0.5)

    # EMA smoothing with hard resets at scene cuts and a pan-speed clamp.
    smooth: list[float] = []
    state = raw[0]
    cut_idx = {int(round(c * SAMPLE_HZ)) for c in cuts}
    max_step = MAX_PAN_PER_S / SAMPLE_HZ
    for k, value in enumerate(raw):
        if k in cut_idx:
            state = value
        else:
            target_state = state + EMA_ALPHA * (value - state)
            state = state + float(np.clip(target_state - state, -max_step, max_step))
        smooth.append(state)

    def to_offset(centre: float) -> int:
        size = crop_w if axis == "x" else crop_h
        off = int(round(centre * (src_w if axis == "x" else src_h) - size / 2))
        return int(max(0, min(span, off)))

    # 1 Hz keyframes (+ explicit jumps at cuts) keep the expression short.
    keyframes: list[tuple[float, int]] = []
    for k in range(0, n, int(SAMPLE_HZ)):
        keyframes.append((k / SAMPLE_HZ, to_offset(smooth[k])))
    for c in cuts:
        k = min(n - 1, int(round(c * SAMPLE_HZ)))
        keyframes.append((max(0.0, c - 0.001), to_offset(smooth[max(0, k - 1)])))
        keyframes.append((c, to_offset(smooth[k])))
    keyframes.append((duration, to_offset(smooth[-1])))
    keyframes.sort(key=lambda kv: kv[0])
    n_faces = sum(1 for f in faces if f is not None)
    log.info("crop plan: axis=%s faces in %d/%d samples, %d keyframes", axis, n_faces, n, len(keyframes))
    return CropPlan(crop_w, crop_h, axis, keyframes)
