from __future__ import annotations

from pathlib import Path

import pytest

from viral_clipper.analysis.analyze import analyze, load_cached
from viral_clipper.analysis.transcribe import build_sentences
from viral_clipper.config import Config
from viral_clipper.ingest.source import resolve_source
from viral_clipper.models import Word


def test_analyze_finds_the_two_loud_bursts_and_cuts(sample_video: Path, test_config: Config) -> None:
    video, work_dir = resolve_source(str(sample_video), test_config)
    assert 39.0 <= video.duration <= 41.0
    assert video.width == 640 and video.height == 360

    seen: list[float] = []
    result = analyze(video, work_dir, test_config, progress=lambda f, _m: seen.append(f))
    assert seen == sorted(seen) and seen[-1] <= 1.0, "progress must be monotonic"

    spikes = [e.time for e in result.events if e.kind == "audio_spike"]
    assert any(9.5 <= t <= 11.5 for t in spikes), spikes
    assert any(24.5 <= t <= 26.5 for t in spikes), spikes

    # Two hard scene changes were authored into the sample.
    assert any(9.0 <= c <= 11.0 for c in result.scene_cuts), result.scene_cuts
    assert any(24.0 <= c <= 26.0 for c in result.scene_cuts), result.scene_cuts

    motion = result.curves["motion"]
    middle = sum(motion.slice(12, 24)) / max(1, len(motion.slice(12, 24)))
    tail = sum(motion.slice(28, 39)) / max(1, len(motion.slice(28, 39)))
    assert middle > tail, "the mandelbrot section must read as more motion than the static bars"

    assert len(result.motion_centroids) == len(motion.values)

    # Second call must hit the cache.
    cached = load_cached(work_dir, result.fingerprint)
    assert cached is not None and cached.fingerprint == result.fingerprint


def test_build_sentences_splits_on_punctuation_and_pauses() -> None:
    words = [
        Word(text="Hello", start=0.0, end=0.3),
        Word(text="there.", start=0.35, end=0.6),
        Word(text="Long", start=0.7, end=0.9),
        Word(text="pause", start=1.0, end=1.2),
        Word(text="after", start=3.0, end=3.2),
        Word(text="this", start=3.3, end=3.5),
    ]
    sentences = build_sentences(words, pause_s=0.6)
    assert [s.text for s in sentences] == ["Hello there.", "Long pause", "after this"]
    assert sentences[1].end == 1.2 and sentences[2].start == 3.0


@pytest.mark.slow
def test_real_transcription_backend(sample_video: Path, test_config: Config) -> None:
    cfg = test_config.model_copy(deep=True)
    cfg.whisper.backend = "auto"
    cfg.whisper.model = "tiny"
    video, work_dir = resolve_source(str(sample_video), cfg)
    result = analyze(video, work_dir, cfg, force=True)
    assert result.transcript.backend in {"mlx", "faster_whisper"}
    text = " ".join(w.text for w in result.transcript.words).lower()
    assert any(k in text for k in ("thousand", "dollars", "100", "wait for it", "twist", "insane")), text
    assert len(result.transcript.sentences) >= 3
