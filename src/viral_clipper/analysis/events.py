"""Fuse motion, audio onsets and scene cuts into 'something just happened' events.

This is the MVP stand-in for explosion/crash/kill detection in gameplay: a real event
usually lights up all three channels within a second.
"""

from __future__ import annotations

import numpy as np

from viral_clipper.analysis.audio import local_maxima, rolling_z
from viral_clipper.models import Event, SignalCurve


def fuse_events(
    motion: SignalCurve,
    audio_onset: SignalCurve,
    scene_cuts: list[float],
    rate_hz: float,
    threshold: float = 2.0,
) -> tuple[SignalCurve, list[Event]]:
    n = min(len(motion.values), len(audio_onset.values))
    if n == 0:
        return SignalCurve(name="event", rate_hz=rate_hz, values=[]), []
    m = np.asarray(motion.values[:n], dtype=np.float32)
    o = np.asarray(audio_onset.values[:n], dtype=np.float32)
    window = int(10 * rate_hz)
    mz = np.clip(rolling_z(m, window), 0, None)
    oz = np.clip(rolling_z(o, window), 0, None)

    cut_track = np.zeros(n, dtype=np.float32)
    for t in scene_cuts:
        i = int(round(t * rate_hz))
        lo, hi = max(0, i - int(rate_hz // 2)), min(n, i + int(rate_hz // 2) + 1)
        cut_track[lo:hi] = 1.0

    fused = 0.45 * mz + 0.4 * oz + 0.6 * cut_track * np.minimum(1.0, (mz + oz) / 2)
    # Light smoothing so a 250 ms misalignment between channels still fuses.
    kernel = np.ones(3, dtype=np.float32) / 3
    fused = np.convolve(fused, kernel, mode="same")

    events = [
        Event(time=i / rate_hz, strength=float(fused[i]), kind="action")
        for i in local_maxima(fused, threshold, int(rate_hz))
    ]
    return SignalCurve(name="event", rate_hz=rate_hz, values=fused.tolist()), events
