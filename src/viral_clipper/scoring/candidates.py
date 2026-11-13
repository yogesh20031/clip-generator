"""Candidate window generation and non-overlap selection."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from viral_clipper.models import AnalysisResult, Candidate


@dataclass(frozen=True)
class Window:
    start: float
    end: float
    on_sentences: bool  # both edges are sentence boundaries
    # A non-contiguous edit (source-time ranges in play order); empty = the single range start..end.
    segments: tuple[tuple[float, float], ...] = ()
    # Pre-computed (context_completeness, reason) for story edits, which know their own context.
    context: tuple[float, str] | None = None

    @property
    def parts(self) -> tuple[tuple[float, float], ...]:
        return self.segments or ((self.start, self.end),)


def _snap_to_cut(t: float, cuts: np.ndarray, before: float = 0.8, after: float = 0.3) -> float:
    """Start a clip on a shot boundary if one sits just before (or barely after) the sentence."""
    if cuts.size == 0:
        return t
    near = cuts[(cuts >= t - before) & (cuts <= t + after)]
    return float(near.max()) if near.size else t


def generate_windows(
    result: AnalysisResult,
    min_len: float,
    max_len: float,
    pre_roll: float,
    post_roll: float,
) -> list[Window]:
    duration = result.video.duration
    cuts = np.asarray(result.scene_cuts, dtype=np.float32)
    windows: list[Window] = []
    seen: set[tuple[int, int]] = set()

    def add(start: float, end: float, on_sentences: bool) -> None:
        start = max(0.0, start)
        end = min(duration, end)
        if end - start < min_len or end - start > max_len + pre_roll + post_roll:
            return
        key = (int(start * 10), int(end * 10))
        if key in seen:
            return
        seen.add(key)
        windows.append(Window(start=start, end=end, on_sentences=on_sentences))

    sentences = result.transcript.sentences
    for i, s in enumerate(sentences):
        start = _snap_to_cut(s.start - pre_roll, cuts)
        for j in range(i, len(sentences)):
            e = sentences[j]
            span = e.end - s.start
            if span > max_len:
                break
            if span >= min_len:
                add(start, e.end + post_roll, True)

    # Gameplay with little speech: fall back to shot boundaries and a coarse grid.
    if len(windows) < 20:
        anchors = sorted({0.0, *[float(c) for c in cuts], *np.arange(0.0, duration, 5.0).tolist()})
        for i, a in enumerate(anchors):
            for b in anchors[i + 1 :]:
                if b - a > max_len:
                    break
                if b - a >= min_len:
                    add(a, b, False)
    return windows


def _core(c: Candidate) -> tuple[float, float]:
    return (c.core_start if c.core_start is not None else c.start, c.core_end if c.core_end is not None else c.end)


def select_non_overlapping(
    candidates: list[Candidate], num_clips: int, min_gap: float, taken: list[Candidate] | None = None
) -> list[Candidate]:
    """Greedy by score; a candidate is kept only if its core stays `min_gap` away from every kept one.

    Story edits may share a setup line (the premise), so only the core (escalation → reaction) counts.
    `taken` are clips already chosen elsewhere that new picks must not overlap.
    """
    chosen: list[Candidate] = []
    blocked = list(taken or [])
    for cand in sorted(candidates, key=lambda c: c.score, reverse=True):
        a, b = _core(cand)
        if all(b + min_gap <= _core(k)[0] or a >= _core(k)[1] + min_gap for k in chosen + blocked):
            chosen.append(cand)
            if len(chosen) >= num_clips:
                break
    return sorted(chosen, key=lambda c: c.score, reverse=True)
