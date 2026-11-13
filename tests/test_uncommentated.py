"""Raw gameplay with no commentary: whisper hallucinations, action-window fallback, credit, wording."""

from __future__ import annotations

from test_stories import story_analysis

from viral_clipper.analysis.transcribe import drop_hallucinations
from viral_clipper.config import load_config, load_profile
from viral_clipper.metadata.templates import TemplateEngine
from viral_clipper.models import Candidate, Platform, Segment, Sentence, Transcript, VideoInfo, Word
from viral_clipper.pipeline import is_commentated


def _sentence(start: float, text: str, prob: float) -> Sentence:
    words = [
        Word(text=t, start=start + i * 0.3, end=start + i * 0.3 + 0.25, prob=prob) for i, t in enumerate(text.split())
    ]
    return Sentence(text=text, start=words[0].start, end=words[-1].end, words=words)


def _transcript(lines: list[tuple[float, str, float]]) -> Transcript:
    sentences = [_sentence(*line) for line in lines]
    return Transcript(language="en", words=[w for s in sentences for w in s.words], sentences=sentences)


def test_gameplay_noise_is_dropped() -> None:
    noise = _transcript(
        [
            (2.0, "Interesting 쓰ír", 0.0),
            (31.0, "According to Rob Smith's", 0.29),
            (129.0, "We'll be right back.", 0.55),
            (141.0, "Mount rhoax has failed his trace already with city championship shots", 0.0),
            (160.0, "Contentña tends to remain дав высolia", 0.08),
            (272.0, "Aye...", 0.08),
        ]
    )
    assert drop_hallucinations(noise, 0.4).is_empty


def test_real_shouts_next_to_speech_survive() -> None:
    talk = _transcript(
        [
            (10.0, "If you make this shot I will give you the money.", 0.85),
            (16.0, "Oh!", 0.12),
            (18.0, "I just did it!", 0.38),
            (300.0, "Yeah!", 0.05),  # nothing confident nearby: noise
        ]
    )
    kept = [s.text for s in drop_hallucinations(talk, 0.4).sentences]
    assert kept == ["If you make this shot I will give you the money.", "Oh!", "I just did it!"]


def test_wordless_video_gets_action_windows() -> None:
    result = story_analysis()
    assert is_commentated(result, load_config().clip.min_speech_wpm)
    silent = result.model_copy(update={"transcript": Transcript()})
    assert not is_commentated(silent, load_config().clip.min_speech_wpm)


def _cand() -> Candidate:
    return Candidate(
        start=60.0,
        end=175.0,
        score=70,
        peak_time=150.0,
        features={},
        contributions=[],
        reasons=[],
        transcript_text="",
        hook_pattern="wait_for_it",
        segments=[Segment(start=60.0, end=70.0), Segment(start=140.0, end=175.0)],
    )


def test_gta5_source_is_not_sold_as_gta6_and_is_credited() -> None:
    video = VideoInfo(
        path="x.mp4",
        title="GTA 5 Crazy MEGA RAMP No Copyright Gameplay",
        slug="x",
        duration=546,
        width=3840,
        height=2160,
        fps=60,
        source_url="https://www.youtube.com/watch?v=abc",
        channel="Some Channel",
        license="Creative Commons Attribution license (reuse allowed)",
    )
    engine = TemplateEngine(load_profile("gta6"), video.title, video.credit)
    for seed in range(12):
        hook, meta = engine.bundle(_cand(), seed, list(Platform))
        for m in meta.values():
            blob = " ".join([m.title, m.description, *m.hashtags]).lower()
            assert "gta 6" not in blob and "gta6" not in blob and "vice city" not in blob, blob
            assert m.description.endswith("Gameplay: Some Channel — https://www.youtube.com/watch?v=abc (CC BY)")
            assert "\n\n\n" not in m.description
        assert "150" not in hook, "hook times are clip times, not source times"


def test_hook_time_is_clip_time() -> None:
    from viral_clipper.metadata.templates import _clip_time

    assert _clip_time(_cand(), 150.0) == 10.0 + 10.0
    assert _clip_time(_cand(), 65.0) == 5.0


def test_manual_hook_leads_title_and_description() -> None:
    engine = TemplateEngine(load_profile("gta6"), "GTA 5 mega ramp", "")
    hook, meta = engine.bundle(_cand(), 3, [Platform.INSTAGRAM_REELS], hook="Rocket car vs the biggest ramp")
    m = meta[Platform.INSTAGRAM_REELS]
    assert hook == m.hook == m.title == "Rocket car vs the biggest ramp"
    assert m.description.startswith("Rocket car vs the biggest ramp")
