"""Per-video normalization of raw analysis curves onto 0-1 so profile weights are comparable."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from viral_clipper.models import AnalysisResult, Event, Transcript


def robust_unit(values: np.ndarray, lo_pct: float = 5.0, hi_pct: float = 95.0) -> np.ndarray:
    """Scale to 0-1 between the 5th and 95th percentile; flat inputs become zeros."""
    if values.size == 0:
        return values.astype(np.float32)
    lo, hi = np.percentile(values, [lo_pct, hi_pct])
    if hi - lo < 1e-6:
        return np.zeros_like(values, dtype=np.float32)
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)


@dataclass
class SignalContext:
    """Everything the scorer needs, pre-normalized once per video."""

    rate_hz: float
    duration: float
    audio_z: np.ndarray  # rolling loudness z-score, clipped 0..4 then /4
    audio_level: np.ndarray  # robust-unit RMS dB
    onset: np.ndarray
    motion: np.ndarray
    event: np.ndarray
    silence: np.ndarray
    scene_cuts: np.ndarray
    events: list[Event]
    transcript: Transcript
    median_wps: float

    def idx(self, t: float) -> int:
        return int(max(0, min(len(self.motion) - 1, round(t * self.rate_hz))))

    def window(self, arr: np.ndarray, start: float, end: float) -> np.ndarray:
        a = self.idx(start)
        b = max(a + 1, self.idx(end))
        return arr[a:b]

    @classmethod
    def from_analysis(cls, result: AnalysisResult) -> SignalContext:
        rate = result.curves["motion"].rate_hz
        n = len(result.curves["motion"].values)

        def arr(name: str) -> np.ndarray:
            vals = np.asarray(result.curves[name].values, dtype=np.float32) if name in result.curves else np.zeros(n)
            if vals.size < n:
                vals = np.pad(vals, (0, n - vals.size))
            return vals[:n]

        audio_z = np.clip(arr("audio_rms_z"), 0.0, 4.0) / 4.0
        wps = _words_per_second(result.transcript, rate, n)
        return cls(
            rate_hz=rate,
            duration=result.video.duration,
            audio_z=audio_z,
            audio_level=robust_unit(arr("audio_rms_db")),
            onset=robust_unit(arr("audio_onset")),
            motion=robust_unit(arr("motion")),
            event=robust_unit(arr("event")),
            silence=np.clip(arr("silence"), 0.0, 1.0),
            scene_cuts=np.asarray(result.scene_cuts, dtype=np.float32),
            events=result.events,
            transcript=result.transcript,
            median_wps=float(np.median(wps[wps > 0])) if np.any(wps > 0) else 0.0,
        )


def _words_per_second(transcript: Transcript, rate_hz: float, n: int) -> np.ndarray:
    """Word onsets binned onto the grid and smoothed over 3 s."""
    counts = np.zeros(n, dtype=np.float32)
    for w in transcript.words:
        i = int(round(w.start * rate_hz))
        if 0 <= i < n:
            counts[i] += 1
    k = max(1, int(3 * rate_hz))
    smooth = np.convolve(counts, np.ones(k, dtype=np.float32), mode="same")
    return smooth * rate_hz / k  # words per second
