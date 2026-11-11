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


def test_crop_expression_is_piecewise_linear_and_flat() -> None:
    plan = CropPlan(crop_w=608, crop_h=1080, axis="x", keyframes=[(0.0, 100), (1.0, 200), (2.0, 200)])
    expr = plan.expression()
    assert "gte(t,0.000)*lt(t,1.000)*(100+(200-100)*(t-0.000)/1.000)" in expr
    assert "gte(t,1.000)*lt(t,2.000)*200" in expr and "gte(t,2.000)*200" in expr
    assert expr.startswith("if(isnan(t),100,"), "FFmpeg evaluates with t=NaN while configuring the filter"
    assert expr.count("if(") == 1, "nested ifs hit FFmpeg's 100-level parser limit on fast-cut clips"
    assert CropPlan(608, 1080, "x", [(0.0, 42)]).expression() == "42"


def test_crop_expression_with_hundreds_of_keyframes_runs_in_ffmpeg(tmp_path: Path) -> None:
    import subprocess

    from viral_clipper.ingest.ffprobe import ffmpeg_path

    keyframes = [(k * 0.01, (k * 7) % 300) for k in range(250)]  # 250 keyframes inside 2.5 s
    plan = CropPlan(crop_w=340, crop_h=360, axis="x", keyframes=keyframes)
    out = tmp_path / "crop.mp4"
    cmd = [
        ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=640x360:rate=30:duration=1",
        "-vf",
        f"crop={plan.crop_w}:{plan.crop_h}:x='{plan.expression()}':y=0",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert out.stat().st_size > 0


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
    assert 0.0 <= rendered.thumbnail_time <= 12.6
    assert len(rendered.thumbnail_alternatives) <= test_config.clip.thumbnail_alternatives
    assert all(p.exists() for p in rendered.thumbnail_alternatives)
    assert rendered.srt.read_text(encoding="utf-8").strip(), "captions were written"

    info = probe(rendered.path)
    assert (info.width, info.height) == (1080, 1920)
    assert abs(info.fps - 30) < 0.5
    assert 11.5 <= info.duration <= 12.6
    assert info.has_audio

    lufs = measure_integrated_loudness(rendered.path)
    assert lufs is not None and -17.0 <= lufs <= -11.0, lufs
    assert not (work_dir / ".tmp" / "clip_01").exists(), "temp frames are cleaned up"
