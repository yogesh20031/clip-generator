import pytest
from pydantic import ValidationError

from viral_clipper.plan import EditPlan, PlanClip, apply_fixes, check_clip
from viral_clipper.render.cover import FrameScore, choose


def _clip(**kw):
    base = {"hook": "h", "instagram_caption": "c", "youtube_title": "t", "youtube_description": "d"}
    return PlanClip(**(base | kw))


def test_check_clip_accepts_whole_sentences():
    check = check_clip("Time for a ride on the world's cheapest plane ticket. We survived.", 47)
    assert check.ok and not check.warnings


def test_check_clip_rejects_dangling_opener_and_cut_off_ending():
    check = check_clip("And now the most expensive plane ticket on the planet and then we", 60)
    assert not check.ok
    assert any("mid-thought" in e for e in check.errors)
    assert any("ends mid-sentence" in e for e in check.errors)


def test_check_clip_length_limits():
    assert check_clip("Short and sweet.", 75).warnings
    assert not check_clip("Short and sweet.", 90).ok


def test_check_clip_warns_on_lowercase_opening():
    check = check_clip("we're gonna fly on the cheapest plane. We survived.", 40)
    assert check.ok and check.warnings


def test_apply_fixes_rewrites_words_and_sentences():
    analysis = {
        "transcript": {
            "words": [{"text": "Carl's"}, {"text": "mom"}, {"text": "Carlos"}],
            "sentences": [{"text": "I love Carl's mom", "words": [{"text": "Carl,"}]}],
        }
    }
    assert apply_fixes(analysis, {"Carl": "Karl"}) == 2
    t = analysis["transcript"]
    assert [w["text"] for w in t["words"]] == ["Karl's", "mom", "Carlos"]  # whole words only
    assert t["sentences"][0]["text"] == "I love Karl's mom"
    assert t["sentences"][0]["words"][0]["text"] == "Karl,"


def test_plan_clip_needs_footage():
    with pytest.raises(ValidationError):
        _clip()
    with pytest.raises(ValidationError):
        _clip(segs=["12"])
    assert _clip(ids=[1, 2]).ids == [1, 2]


def test_plan_parses():
    plan = EditPlan.model_validate(
        {"source": "https://youtu.be/x", "niche": "mrbeast", "fixes": {"Carl": "Karl"}, "clips": [
            {"segs": ["1:00-1:30"], "hook": "h", "instagram_caption": "c", "youtube_title": "t",
             "youtube_description": "d"}]}
    )
    assert plan.clips[0].segs == ["1:00-1:30"]


def test_cover_prefers_hook_frame_with_a_clear_face():
    hook = FrameScore(0.8, face_area=0.05, face_sharpness=300)
    frames = [FrameScore(10, 0.2, 400)]
    assert choose(frames, hook) == 0.8


def test_cover_skips_blurry_faces():
    hook = FrameScore(0.8, face_area=0.0, face_sharpness=0)
    frames = [FrameScore(5, 0.3, 20), FrameScore(9, 0.08, 250)]  # big but smeared vs smaller and sharp
    assert choose(frames, hook) == 9


def test_cover_falls_back_to_hook_without_faces():
    assert choose([], FrameScore(0.8, 0, 0)) == 0.8
