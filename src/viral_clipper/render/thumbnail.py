"""Pick the thumbnail frame for click-through, not just "the loudest second".

Research (docs/research.md §4.2): high-CTR frames show a dominant face/reaction, high contrast and a
sharp image. We sample the rendered clip at 2 fps, score each frame on those, bias towards the payoff
moment, and save the best frame plus a few alternates so the creator can choose.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from viral_clipper.render.crop import _iter_bgr_frames
from viral_clipper.render.ffmpeg import write_thumbnail

log = logging.getLogger(__name__)

SAMPLE_HZ = 2.0
SCORE_W, SCORE_H = 270, 480  # 9:16 analysis raster
MIN_SEPARATION_S = 2.0


@dataclass(frozen=True)
class ThumbnailPick:
    path: Path
    time: float
    alternatives: list[Path]
    score: float


def _frame_scores(clip_path: Path, duration: float, face_model: Path) -> list[tuple[float, float]]:
    """(time, score) per sampled frame."""
    import cv2

    detector = None
    if face_model.exists():
        detector = cv2.FaceDetectorYN.create(str(face_model), "", (SCORE_W, SCORE_H), 0.6, 0.3, 50)
    raw: list[tuple[float, float, float, float]] = []
    for i, frame in enumerate(_iter_bgr_frames(clip_path, 0.0, duration, SCORE_W, SCORE_H)):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if gray.mean() < 20:  # black / fade frame
            continue
        contrast = float(gray.std())
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        face_area = 0.0
        if detector is not None:
            _, faces = detector.detect(frame)
            if faces is not None and len(faces):
                face_area = float(max(f[2] * f[3] for f in faces)) / (SCORE_W * SCORE_H)
        raw.append((i / SAMPLE_HZ, face_area, contrast, sharpness))
    if not raw:
        return []
    max_sharp = max(r[3] for r in raw) or 1.0
    scores: list[tuple[float, float]] = []
    for t, face, contrast, sharp in raw:
        face_term = min(1.0, face / 0.12)  # a face covering ~12% of the frame is already "big"
        contrast_term = min(1.0, contrast / 64.0)
        sharp_term = sharp / max_sharp
        scores.append((t, 0.45 * face_term + 0.25 * contrast_term + 0.2 * sharp_term))
    return scores


def pick_thumbnail(
    clip_path: Path,
    duration: float,
    peak_rel: float,
    face_model: Path,
    dest: Path,
    alternatives: int = 2,
) -> ThumbnailPick:
    scores = _frame_scores(clip_path, duration, face_model)
    if not scores:
        write_thumbnail(clip_path, max(0.0, peak_rel), dest)
        return ThumbnailPick(path=dest, time=peak_rel, alternatives=[], score=0.0)
    # Prefer frames near the payoff; the reaction usually lives right after the peak.
    ranked = sorted(
        ((t, s + 0.1 * float(np.exp(-0.5 * ((t - peak_rel - 1.0) / 4.0) ** 2))) for t, s in scores),
        key=lambda ts: ts[1],
        reverse=True,
    )
    chosen: list[tuple[float, float]] = []
    for t, s in ranked:
        if all(abs(t - c[0]) >= MIN_SEPARATION_S for c in chosen):
            chosen.append((t, s))
        if len(chosen) > alternatives:
            break
    best_t, best_s = chosen[0]
    write_thumbnail(clip_path, best_t, dest)
    alts: list[Path] = []
    for k, (t, _s) in enumerate(chosen[1:], start=1):
        alt = dest.with_name(f"{dest.stem}_alt{k}{dest.suffix}")
        write_thumbnail(clip_path, t, alt)
        alts.append(alt)
    log.info("thumbnail for %s at %.1fs (score %.2f, %d alternates)", clip_path.name, best_t, best_s, len(alts))
    return ThumbnailPick(path=dest, time=round(best_t, 2), alternatives=alts, score=round(best_s, 3))
