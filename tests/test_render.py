from __future__ import annotations

from pathlib import Path

from viral_clipper.analysis.analyze import analyze
from viral_clipper.config import Config
from viral_clipper.ingest.ffprobe import probe
from viral_clipper.ingest.source import resolve_source
from viral_clipper.models import Candidate, Transcript, Word
from viral_clipper.render.captions import group_lines
from viral_clipper.render.clip import render_clip
from viral_clipper.render.crop import CropPlan
from viral_clipper.render.ffmpeg import measure_integrated_loudness


def test_group_lines_breaks_on_count_pause_and_punctuation() -> None:
    words = [
        Word(text=t, start=i * 0.3, end=i * 0.3 + 0.25) for i, t in enumerate("one two three four five six.".split())
    ]
    words.append(Word(text="later", start=5.0, end=5.3))
    lines = group_lines(words, words_per_line=3)
    assert [ln.text for ln in lines] == ["one two three", "four five six.", "later"]


def test_crop_expression_is_piecewise_linear() -> None:
    plan = CropPlan(crop_w=608, crop_h=1080, axis="x", keyframes=[(0.0, 100), (1.0, 200), (2.0, 200)])
    expr = plan.expression()
    assert expr.startswith("if(lt(t,1.000),100+(200-100)*(t-0.000)/1.000,")
    assert expr.count("if(") == 2 and expr.endswith("200))")
    assert CropPlan(608, 1080, "x", [(0.0, 42)]).expression() == "42"


def test_render_clip_produces_vertical_captioned_normalized_mp4(
    sample_video: Path, test_config: Config, transcript: Transcript
) -> None:
    video, work_dir = resolve_source(str(sample_video), test_config)
    analysis = analyze(video, work_dir, test_config).model_copy(update={"transcript": transcript})
    cand = Candidate(
        start=8.0,
        end=20.0,
        score=77.0,
        peak_time=10.0,
        features={},
        contributions=[],
        reasons=["loud spike at 0:10"],
        transcript_text=transcript.text_between(8.0, 20.0),
        hook_pattern="wait_for_it",
    )
    rendered = render_clip(analysis, cand, 1, "WAIT FOR IT…", work_dir, test_config)
    assert rendered.path.exists() and rendered.thumbnail.exists()
    assert rendered.srt.read_text(encoding="utf-8").strip(), "captions were written"

    info = probe(rendered.path)
    assert (info.width, info.height) == (1080, 1920)
    assert abs(info.fps - 30) < 0.5
    assert 11.5 <= info.duration <= 12.6
    assert info.has_audio

    lufs = measure_integrated_loudness(rendered.path)
    assert lufs is not None and -17.0 <= lufs <= -11.0, lufs
    assert not (work_dir / ".tmp" / "clip_01").exists(), "temp frames are cleaned up"
