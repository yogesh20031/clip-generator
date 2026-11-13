"""Story mode: segmentation, context closure, condensed edits, multi-segment rendering."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from viral_clipper.analysis.analyze import analyze
from viral_clipper.config import Config, load_config, load_profile
from viral_clipper.ingest.ffprobe import probe
from viral_clipper.ingest.source import resolve_source
from viral_clipper.models import (
    AnalysisResult,
    Candidate,
    Segment,
    Sentence,
    SignalCurve,
    Transcript,
    VideoInfo,
    Word,
)
from viral_clipper.render.captions import clip_timeline_words
from viral_clipper.render.clip import render_clip, to_clip_time
from viral_clipper.render.ffmpeg import measure_integrated_loudness
from viral_clipper.scoring.edits import build_edit, score_stories
from viral_clipper.scoring.signals import SignalContext
from viral_clipper.scoring.stories import build_story_model, format_amount, parse_amounts, pick_payoffs

RATE = 4.0
DURATION = 200.0

# Two stories. Story 1 (Khalid) has a setup, 50 s of filler, a loud speechless shot and a result;
# story 2 (Speed) starts on a spoken transition.
SCRIPT: list[tuple[float, str]] = [
    (0.5, "In this video two people compete for real money."),
    (4.0, "Starting with Khalid, a normal guy from the crowd."),
    (8.0, "If Khalid can beat Ronaldo, I will give him a million dollars."),
    (14.0, "Ronaldo is the greatest football player on the planet."),
    *[(18.0 + 3.0 * i, "Okay.") for i in range(14)],
    (62.0, "Khalid, this is your last shot at the target."),
    # 66-70 s: no speech, loud crowd + motion = the shot
    (71.0, "Oh my god, Khalid won the million dollars!"),
    (74.5, "He actually did it, that is insane!"),
    (79.0, "Yeah."),
    (100.0, "For our next challenge, we have Speed."),
    (104.0, "If Speed wins the race, he gets fifty grand."),
    *[(110.0 + 3.0 * i, "Alright.") for i in range(10)],
    (142.0, "Speed is running as fast as he can now."),
    (150.0, "Speed lost the race, no way!"),
    (154.0, "That was so close, I can't believe it."),
]


def _sentence(start: float, text: str) -> Sentence:
    tokens = text.split()
    step = 0.32
    words = [Word(text=t, start=start + i * step, end=start + i * step + 0.26) for i, t in enumerate(tokens)]
    return Sentence(text=text, start=words[0].start, end=words[-1].end, words=words)


def story_analysis(video_path: str = "/nonexistent.mp4") -> AnalysisResult:
    sentences = [_sentence(t, s) for t, s in SCRIPT]
    words = [w for s in sentences for w in s.words]
    n = int(DURATION * RATE)
    t = np.arange(n) / RATE
    motion = np.full(n, 0.1)
    audio_z = np.zeros(n)
    event = np.zeros(n)
    for a, b, level in ((66.0, 70.5, 1.0), (150.0, 152.0, 0.8)):
        mask = (t >= a) & (t <= b)
        motion[mask] = 1.0
        audio_z[mask] = 3.5
        event[mask] = level
    curves = {
        "motion": SignalCurve(name="motion", rate_hz=RATE, values=motion.tolist()),
        "audio_rms_z": SignalCurve(name="audio_rms_z", rate_hz=RATE, values=audio_z.tolist()),
        "audio_rms_db": SignalCurve(name="audio_rms_db", rate_hz=RATE, values=(-30 + 10 * (audio_z > 0)).tolist()),
        "event": SignalCurve(name="event", rate_hz=RATE, values=event.tolist()),
        "silence": SignalCurve(name="silence", rate_hz=RATE, values=np.zeros(n).tolist()),
    }
    video = VideoInfo(path=video_path, title="t", slug="t", duration=DURATION, width=1920, height=1080, fps=30)
    return AnalysisResult(
        fingerprint="x",
        video=video,
        transcript=Transcript(words=words, sentences=sentences, backend="fake"),
        scene_cuts=[99.5],
        curves=curves,
        events=[],
    )


def _covered(parts: list[Segment], t: float) -> bool:
    return any(s.start <= t <= s.end for s in parts)


def test_parse_amounts_reads_spoken_money() -> None:
    assert parse_amounts("that's another $100 ,000 for your charity") == [100_000]
    assert parse_amounts("I will give him a million dollars") == [1_000_000]
    assert parse_amounts("this hundred grand") == [100_000]
    assert parse_amounts("40 grand is a good chunk") == [40_000]
    assert parse_amounts("100 million people watching") == []
    assert format_amount(1_000_000) == "$1M" and format_amount(100_000) == "$100K" and format_amount(500) == "$500"


def test_premise_card_text_is_tidy() -> None:
    from viral_clipper.scoring.edits import _premise

    assert _premise([], [100_000], "$100 ,000 on the line and a half -court shot.") == (
        "$100,000 on the line and a half-court shot."
    )
    assert _premise(["Khalid", "Ronaldo"], [1_000_000], "") == "Khalid vs Ronaldo for $1M"


def test_stories_split_on_spoken_transitions() -> None:
    model = build_story_model(story_analysis(), load_profile("mrbeast"), min_story_s=20)
    starts = [round(s.start) for s in model.stories]
    assert len(model.stories) == 2, starts
    assert model.stories[1].units[0].text.startswith("For our next challenge")
    assert {"khalid", "ronaldo"} <= set(model.stories[0].names)


def test_payoff_is_the_confirmed_result_not_the_setup() -> None:
    model = build_story_model(story_analysis(), load_profile("mrbeast"), min_story_s=20)
    story = model.stories[0]
    payoffs = [story.units[i] for i in pick_payoffs(story)]
    assert any(66 <= u.start <= 72 for u in payoffs), [(u.start, u.text) for u in payoffs]
    assert not any(u.start < 15 for u in payoffs), "the stakes line is not a payoff"


def test_edit_keeps_context_and_payoff_and_cuts_filler() -> None:
    result = story_analysis()
    cfg = load_config()
    model = build_story_model(result, load_profile("mrbeast"), min_story_s=20)
    story = model.stories[0]
    ctx = SignalContext.from_analysis(result)
    final = pick_payoffs(story)[-1]
    plan = build_edit(model, story, final, ctx, cfg.clip, 20, 45, 30, DURATION)
    assert plan is not None
    segs = plan.segments
    assert _covered(segs, 9.0), "the stakes line (who + what is at stake) is in the clip"
    assert _covered(segs, 68.0), "the speechless shot is kept"
    assert _covered(segs, 72.0), "the result line is kept"
    assert _covered(segs, 75.0), "the reaction is kept"
    assert not _covered(segs, 79.1), "nothing after the reaction"
    assert 20 <= plan.duration <= 45
    assert len(segs) >= 2, "filler between setup and payoff is jump-cut out"
    okays_kept = sum(1 for k in range(14) if _covered(segs, 18.2 + 3.0 * k))
    assert okays_kept <= 3, okays_kept
    assert "Khalid" in plan.premise and "$1M" in plan.premise, plan.premise
    assert plan.coverage >= 0.8, plan.coverage_detail


def test_score_stories_returns_one_story_per_clip() -> None:
    cfg = load_config()
    selected, edits, model = score_stories(story_analysis(), load_profile("mrbeast"), 2, 20, 45, cfg.clip)
    assert edits and len(selected) == 2
    story_clips = [c for c in selected if c.story is not None]
    assert {c.story.story_index for c in story_clips} == {0, 1}, [c.story for c in story_clips]
    for c in story_clips:
        assert c.duration <= 45 + 0.01
        assert c.features["context_completeness"] >= cfg.clip.min_context
        assert c.reasons[0].startswith("story:")


def test_clip_timeline_words_remaps_and_breaks_at_cuts() -> None:
    words_a = [Word(text="Win", start=10.0, end=10.3), Word(text="$100", start=10.4, end=10.7)]
    words_a.append(Word(text=",000", start=10.7, end=11.0))
    words_b = [Word(text="He", start=50.0, end=50.2), Word(text="did", start=50.3, end=50.6)]
    parts = [(9.9, 11.2), (49.9, 50.8)]
    durations = [b - a for a, b in parts]
    out, breaks = clip_timeline_words([words_a, words_b], parts, durations)
    assert [w.text for w in out] == ["Win", "$100,000", "He", "did"]
    assert abs(out[2].start - (durations[0] + 0.1)) < 1e-6
    assert breaks == {0, 2}
    assert abs(to_clip_time(parts, durations, 50.3) - (durations[0] + 0.4)) < 1e-6
    assert to_clip_time(parts, durations, 30.0) == durations[0]  # cut-out time maps to the nearest kept edge


def test_render_multi_segment_edit(sample_video: Path, test_config: Config, transcript: Transcript) -> None:
    video, work_dir = resolve_source(str(sample_video), test_config)
    analysis = analyze(video, work_dir, test_config).model_copy(update={"transcript": transcript})
    segments = [Segment(start=1.0, end=5.0), Segment(start=9.5, end=12.5), Segment(start=24.0, end=28.0)]
    cand = Candidate(
        start=1.0,
        end=28.0,
        score=70.0,
        peak_time=25.0,
        features={},
        contributions=[],
        reasons=["story"],
        transcript_text="x",
        hook_pattern="bold_claim",
        segments=segments,
    )
    rendered = render_clip(analysis, cand, 7, "Khalid vs Ronaldo for $1M", work_dir, test_config)
    info = probe(rendered.path)
    assert (info.width, info.height) == (1080, 1920) and info.has_audio
    assert abs(info.duration - 11.0) <= 0.15, info.duration
    lufs = measure_integrated_loudness(rendered.path)
    assert lufs is not None and -17.0 <= lufs <= -11.0, lufs
    srt = rendered.srt.read_text(encoding="utf-8")
    assert srt.strip()
    last_end = srt.strip().splitlines()[-2].split(" --> ")[1]
    h, m, rest = last_end.split(":")
    assert int(h) * 3600 + int(m) * 60 + float(rest.replace(",", ".")) <= 11.0 + 0.3
    # The payoff (25 s in the source) is 4 + 3 + 1 = 8 s into the clip.
    assert 0.0 <= rendered.thumbnail_time <= 11.0
