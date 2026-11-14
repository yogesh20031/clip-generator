"""Render an edit plan: the clips someone chose by reading the transcript, with their hooks and captions.

The plan is written by a person (or Claude in the chat) after reading `viral-clipper stories --all`.
Rendering it is mechanical: fix misheard names, cut each clip, check it opens and closes on whole
sentences, pick a cover, and write the captions file video-uploader posts from.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from viral_clipper.config import Config

# Openers that mean the clip starts mid-thought.
_DANGLING_OPENERS = {"and", "but", "so", "because", "or", "then", "also", "which", "that"}
MAX_LEN_S = 84.0  # 1.4 min: only when the story needs it
TARGET_MAX_S = 70.0


class PlanClip(BaseModel):
    ids: list[int] = Field(default_factory=list, description="sentence ids from `viral-clipper stories`")
    segs: list[str] = Field(default_factory=list, description='source ranges, "START-END" in s or mm:ss')
    hook: str = Field(description="on-screen premise card, a few words")
    instagram_caption: str = Field(description="Instagram/TikTok caption: hook line, tease, credit, hashtags")
    youtube_title: str
    youtube_description: str
    cover_at: float | None = Field(default=None, description="force the cover frame (seconds into the clip)")

    @model_validator(mode="after")
    def _has_footage(self) -> PlanClip:
        if not self.ids and not self.segs:
            raise ValueError(f"clip {self.hook!r} has neither ids nor segs")
        for seg in self.segs:
            if "-" not in seg.lstrip("-"):
                raise ValueError(f"segment {seg!r} should look like START-END")
        return self


class EditPlan(BaseModel):
    source: str
    niche: str = "generic"
    output_dir: str | None = None
    # Whisper's spelling → the right one, e.g. {"Carl": "Karl"}. Applied to the cached transcript.
    fixes: dict[str, str] = Field(default_factory=dict)
    clips: list[PlanClip]


class ClipCheck(BaseModel):
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def check_clip(text: str, duration: float) -> ClipCheck:
    """Does the clip open on a whole sentence and land on one, at a postable length?"""
    out = ClipCheck()
    words = text.strip().split()
    if not words:
        out.errors.append("no speech in the clip")
        return out
    first = re.sub(r"\W", "", words[0]).lower()
    if first in _DANGLING_OPENERS:
        out.errors.append(f"opens mid-thought on {words[0]!r}")
    elif words[0][0].islower():
        out.warnings.append(f"opens on a lowercase word ({words[0]!r}); check it isn't mid-sentence")
    if not re.search(r"[.!?…]['\")]*$", text.strip()):
        out.errors.append(f"ends mid-sentence: …{text.strip()[-40:]!r}")
    if duration > MAX_LEN_S:
        out.errors.append(f"{duration:.0f}s is over the {MAX_LEN_S:.0f}s limit")
    elif duration > TARGET_MAX_S:
        out.warnings.append(f"{duration:.0f}s is long; fine only if the story needs it")
    return out


def apply_fixes(analysis: dict, fixes: dict[str, str]) -> int:
    """Rewrite misheard words everywhere the transcript stores them. Returns words changed."""
    if not fixes:
        return 0
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in fixes) + r")\b")

    def fix(text: str) -> str:
        return pattern.sub(lambda m: fixes[m.group(1)], text)

    changed = 0
    transcript = analysis.get("transcript", {})
    word_lists = [transcript.get("words", [])] + [s.get("words", []) for s in transcript.get("sentences", [])]
    for words in word_lists:
        for w in words:
            new = fix(w["text"])
            if new != w["text"]:
                w["text"] = new
                changed += 1
    for s in transcript.get("sentences", []):
        if isinstance(s.get("text"), str):
            s["text"] = fix(s["text"])
    return changed


def _parse_seg(seg: str) -> tuple[str, str]:
    start, end = seg.lstrip().split("-", 1) if not seg.startswith("-") else ("0", seg[1:])
    return start, end


def render_plan(
    plan: EditPlan, cfg: Config, on_clip: Callable[[dict], None] | None = None
) -> Iterator[dict]:
    """Render each planned clip in order. Yields one entry per clip for the captions file; entries that
    fail their checks carry "error" and should not be posted."""
    from viral_clipper.analysis.analyze import analyze, cache_path
    from viral_clipper.ingest.source import resolve_source
    from viral_clipper.pipeline import _with_output_dir, run_render_edit
    from viral_clipper.render.cover import pick_cover

    cfg_out = _with_output_dir(cfg, plan.output_dir)
    if plan.fixes:
        video, work_dir = resolve_source(plan.source, cfg_out, None)
        analyze(video, work_dir, cfg_out, None)  # make sure the cache exists before patching it
        path = cache_path(work_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        if apply_fixes(data, plan.fixes):
            path.write_text(json.dumps(data), encoding="utf-8")

    for n, clip in enumerate(plan.clips, 1):
        record = run_render_edit(
            plan.source,
            cfg,
            segments=[_parse_seg(s) for s in clip.segs] or None,
            sentence_ids=clip.ids or None,
            niche=plan.niche,
            hook=clip.hook,
            output_dir=plan.output_dir,
            manual_note="plan edit",
        )
        video = Path(record.path)
        check = check_clip(record.transcript_text, record.duration)
        cover = video.parent / "thumbnails" / f"{video.stem}_cover.jpg"
        if clip.cover_at is not None:
            from viral_clipper.render.ffmpeg import write_thumbnail

            write_thumbnail(video, clip.cover_at, cover)
            cover_time = clip.cover_at
        else:
            cover_time = pick_cover(video, record.duration, cfg.face_model_path, cover)
        entry = {
            "plan_index": n,
            "folder": str(video.parent),
            "file": video.name,
            "cover": f"thumbnails/{cover.name}",
            "cover_time": round(cover_time, 2),
            "duration": round(record.duration, 1),
            "hook": clip.hook,
            "opens": " ".join(record.transcript_text.split()[:10]),
            "ends": " ".join(record.transcript_text.split()[-10:]),
            "standalone_ok": check.ok,
            "warnings": check.warnings,
            "youtube_title": clip.youtube_title,
            "youtube_description": clip.youtube_description,
            "instagram_caption": clip.instagram_caption,
        }
        if not check.ok:
            entry["error"] = "; ".join(check.errors)
        if on_clip:
            on_clip(entry)
        yield entry
