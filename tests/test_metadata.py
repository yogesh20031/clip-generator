from __future__ import annotations

import csv
from pathlib import Path

from viral_clipper.config import load_profile
from viral_clipper.metadata.outputs import list_outputs, update_clip_metadata, write_outputs
from viral_clipper.metadata.platforms import apply_rules, rules_for
from viral_clipper.metadata.templates import TemplateEngine
from viral_clipper.models import ALL_PLATFORMS, Candidate, ClipMetadata, ClipRecord, ClipVideoResult, Platform


def _cand(text: str, pattern: str = "curiosity_gap") -> Candidate:
    return Candidate(
        start=10.0,
        end=40.0,
        score=80.0,
        peak_time=32.0,
        features={},
        contributions=[],
        reasons=["x"],
        transcript_text=text,
        hook_pattern=pattern,
    )


def test_template_bundle_fills_placeholders_from_transcript() -> None:
    engine = TemplateEngine(load_profile("mrbeast"))
    cand = _cand("Today we are giving away one hundred thousand dollars, $100,000 to Jimmy. But then he walked away.")
    values = engine.extract_values(cand)
    assert values["amount"] == "100,000"
    assert values["person"] == "Jimmy"
    hook, bundle = engine.bundle(cand, seed=3, platforms=list(ALL_PLATFORMS))
    assert hook and "{" not in hook
    for platform, meta in bundle.items():
        rules = rules_for(platform)
        assert "{" not in meta.title and len(meta.title) <= rules.title_max
        assert len(meta.hashtags) <= rules.hashtag_max and all(h.startswith("#") for h in meta.hashtags)
        assert meta.hook == hook
        assert "dollars" in meta.description or "100,000" in meta.description


def test_apply_rules_caps_and_dedupes_hashtags() -> None:
    title, _d, tags = apply_rules(
        Platform.YOUTUBE_SHORTS, "x " * 80, "desc", ["#GTA6", "gta6", "#GTA", "#Shorts", "#extra"]
    )
    assert tags == ["#GTA6", "#GTA", "#Shorts"]
    assert len(title) <= 100 and title.endswith("…")


def test_gta_hooks_never_leave_empty_placeholders() -> None:
    engine = TemplateEngine(load_profile("gta6"))
    cand = _cand("", pattern="wait_for_it")
    for seed in range(20):
        hook = engine.hook(cand, seed)
        title = engine.title(cand, seed)
        assert "{" not in hook and "{" not in title and len(title) >= 8


def test_outputs_roundtrip_and_update(tmp_path: Path) -> None:
    work = tmp_path / "some-video"
    work.mkdir()
    clip_file = work / "clip_01.mp4"
    clip_file.write_bytes(b"\x00")
    meta = {p: ClipMetadata(platform=p, title="t", description="d", hashtags=["#a"], hook="h") for p in ALL_PLATFORMS}
    record = ClipRecord(
        index=1,
        path=str(clip_file),
        thumbnail_path="",
        srt_path="",
        start=1,
        end=20,
        duration=19,
        score=50,
        reasons=["r"],
        transcript_text="",
        hook="h",
        hook_pattern="shock",
        metadata=meta,
    )
    result = ClipVideoResult(
        video_title="Some Video",
        source="x.mp4",
        output_dir=str(work),
        clips_json=str(work / "clips.json"),
        clips_csv=str(work / "clips.csv"),
        clips=[record],
    )
    write_outputs(result)

    entries = list_outputs(tmp_path)
    assert len(entries) == 1 and entries[0].clip_count == 1

    new = ClipMetadata(
        platform=Platform.TIKTOK,
        title="Better title",
        description="Better desc",
        hashtags=["#fyp", "#mrbeast"],
        hook="New hook",
    )
    updated = update_clip_metadata(clip_file, Platform.TIKTOK, new, tmp_path)
    assert updated.metadata[Platform.TIKTOK].title == "Better title" and updated.hook == "New hook"
    rows = list(csv.DictReader((work / "clips.csv").open(encoding="utf-8")))
    assert {r["platform"] for r in rows} == {p.value for p in ALL_PLATFORMS}
    assert next(r for r in rows if r["platform"] == "tiktok")["title"] == "Better title"
