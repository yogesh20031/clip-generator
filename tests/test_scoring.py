from __future__ import annotations

from pathlib import Path

from viral_clipper.analysis.analyze import analyze
from viral_clipper.config import Config, list_profiles, load_profile
from viral_clipper.ingest.source import resolve_source
from viral_clipper.models import AnalysisResult, Transcript
from viral_clipper.scoring.candidates import select_non_overlapping
from viral_clipper.scoring.scorer import pick_hook_pattern, score_moments


def _analysis_with_transcript(sample_video: Path, cfg: Config, transcript: Transcript) -> AnalysisResult:
    video, work_dir = resolve_source(str(sample_video), cfg)
    result = analyze(video, work_dir, cfg)
    return result.model_copy(update={"transcript": transcript})


def test_profiles_load_and_are_complete() -> None:
    names = list_profiles()
    assert {"gta6", "mrbeast", "generic"} <= set(names)
    for name in names:
        p = load_profile(name)
        assert p.weights["silence_penalty"] < 0
        assert p.hook_templates and p.title_templates
        assert all(len(p.hashtags[k]) >= 2 for k in p.hashtags)


def test_score_moments_prefers_the_action_section(
    sample_video: Path, test_config: Config, transcript: Transcript
) -> None:
    result = _analysis_with_transcript(sample_video, test_config, transcript)
    profile = load_profile("gta6")
    selected, scored = score_moments(
        result, profile, num_clips=3, min_len=8, max_len=20, pre_roll=0.3, post_roll=0.4, min_gap=1.0
    )
    assert scored, "candidate generation produced nothing"
    assert 1 <= len(selected) <= 3
    assert all(0 <= c.score <= 100 for c in scored)
    best = selected[0]
    # The action section spans 10-26 s with loud bursts at 10 s and 25 s: the best clip must land on one.
    assert (best.start <= 10.5 <= best.end) or (best.start <= 25.0 <= best.end), (best.start, best.end, best.reasons)
    assert best.score > 40
    assert best.reasons and all(isinstance(r, str) and r for r in best.reasons)
    # No overlaps among the selected clips.
    for a in selected:
        for b in selected:
            if a is not b:
                assert a.end + 1.0 <= b.start or b.end + 1.0 <= a.start


def test_mrbeast_profile_rewards_money_talk(sample_video: Path, test_config: Config, transcript: Transcript) -> None:
    result = _analysis_with_transcript(sample_video, test_config, transcript)
    profile = load_profile("mrbeast")
    _selected, scored = score_moments(
        result, profile, num_clips=5, min_len=5, max_len=15, pre_roll=0.3, post_roll=0.4, min_gap=1.0
    )
    money_windows = [c for c in scored if "hundred thousand dollars" in c.transcript_text]
    other = [c for c in scored if "dollars" not in c.transcript_text]
    assert money_windows and other
    assert max(c.features["money_number_mentions"] for c in money_windows) > 0
    assert any("mentions" in r for c in money_windows for r in c.reasons)


def test_select_non_overlapping_respects_gap() -> None:
    from viral_clipper.models import Candidate

    def cand(s: float, e: float, score: float) -> Candidate:
        return Candidate(
            start=s,
            end=e,
            score=score,
            peak_time=s,
            features={},
            contributions=[],
            reasons=[],
            transcript_text="",
            hook_pattern="shock",
        )

    picked = select_non_overlapping([cand(0, 10, 90), cand(9, 20, 80), cand(12.5, 25, 70), cand(40, 50, 60)], 10, 2.0)
    assert [(c.start, c.end) for c in picked] == [(0, 10), (12.5, 25), (40, 50)]


def test_pick_hook_pattern_shapes() -> None:
    assert pick_hook_pattern({"payoff_in_window": 1.0, "hook_strength": 0.1}) == "wait_for_it"
    assert pick_hook_pattern({"hook_strength": 0.9, "audio_peak": 0.8}) == "shock"
    assert pick_hook_pattern({"twist_connectives": 0.5}) == "open_loop"
    assert pick_hook_pattern({"money_number_mentions": 0.6}) == "curiosity_gap"
    assert pick_hook_pattern({}) == "bold_claim"
