"""Pick a post cover the way a person would: a big, sharp face, or the hook card when it has one.

The thumbnail picker in thumbnail.py scores sharpness over the whole frame, which let motion-blurred
and cross-faded faces through. Here sharpness is measured on the face itself, so a blurry face loses
to a smaller sharp one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from viral_clipper.render.crop import _iter_bgr_frames
from viral_clipper.render.ffmpeg import write_thumbnail

SCAN_W, SCAN_H = 360, 640
# Frames are sampled at crop.SAMPLE_HZ; the hook card is on screen from the first frames.
HOOK_TIME = 0.8
MIN_FACE_SHARPNESS = 60.0  # Laplacian variance on the face crop; below this the face is smeared
HOOK_FACE_AREA = 0.03  # a face this big next to the hook text makes the hook frame the best cover


@dataclass(frozen=True)
class FrameScore:
    time: float
    face_area: float  # largest face as a share of the frame
    face_sharpness: float

    @property
    def score(self) -> float:
        return self.face_area * math.log(max(self.face_sharpness, 1.0))


def choose(frames: list[FrameScore], hook: FrameScore | None) -> float | None:
    """The cover time: the hook frame when it shows a clear face, else the best sharp face."""
    if hook and hook.face_area >= HOOK_FACE_AREA and hook.face_sharpness >= MIN_FACE_SHARPNESS:
        return hook.time
    sharp = [f for f in frames if f.face_sharpness >= MIN_FACE_SHARPNESS]
    if sharp:
        return max(sharp, key=lambda f: f.score).time
    return hook.time if hook else None


def _score(frame: np.ndarray, detector, time: float) -> FrameScore:
    import cv2

    _, faces = detector.detect(frame)
    if faces is None or not len(faces):
        return FrameScore(time, 0.0, 0.0)
    x, y, w, h = (max(0, int(v)) for v in max(faces, key=lambda f: f[2] * f[3])[:4])
    crop = cv2.cvtColor(frame[y : y + h, x : x + w], cv2.COLOR_BGR2GRAY)
    if crop.size == 0:
        return FrameScore(time, 0.0, 0.0)
    sharpness = float(cv2.Laplacian(crop, cv2.CV_64F).var())
    return FrameScore(time, w * h / (SCAN_W * SCAN_H), sharpness)


def pick_cover(clip_path: Path, duration: float, face_model: Path, dest: Path) -> float:
    """Write the chosen frame to `dest` at full size and return its time in the clip."""
    import cv2

    from viral_clipper.render.crop import SAMPLE_HZ

    detector = cv2.FaceDetectorYN.create(str(face_model), "", (SCAN_W, SCAN_H), 0.7, 0.3, 50)
    frames: list[FrameScore] = []
    hook: FrameScore | None = None
    # Skip the last half second: clips often end on a fade.
    for i, frame in enumerate(_iter_bgr_frames(clip_path, 0.0, max(0.5, duration - 0.5), SCAN_W, SCAN_H)):
        t = i / SAMPLE_HZ
        scored = _score(frame, detector, t)
        if hook is None and t >= HOOK_TIME - 1 / SAMPLE_HZ:
            hook = FrameScore(HOOK_TIME, scored.face_area, scored.face_sharpness)
        elif t > HOOK_TIME:
            frames.append(scored)
    when = choose(frames, hook)
    write_thumbnail(clip_path, HOOK_TIME if when is None else when, dest)
    return HOOK_TIME if when is None else when
