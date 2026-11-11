"""Shot-boundary detection with PySceneDetect's AdaptiveDetector."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def detect_scene_cuts(video_path: str | Path, adaptive_threshold: float, min_scene_len_s: float) -> list[float]:
    """Return cut timestamps in seconds (the start of every scene except the first)."""
    from scenedetect import AdaptiveDetector, detect

    detector = AdaptiveDetector(
        adaptive_threshold=adaptive_threshold,
        min_scene_len=f"{min_scene_len_s}s",
    )
    scenes = detect(str(video_path), detector, show_progress=False)
    cuts = [float(start.seconds) for start, _end in scenes[1:]]
    log.info("scenes: %d cuts", len(cuts))
    return cuts
