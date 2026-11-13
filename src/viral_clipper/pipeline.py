"""End-to-end orchestration shared by the MCP server and the CLI."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from viral_clipper.analysis.analyze import analyze, cache_path
from viral_clipper.config import Config, Profile, load_profile
from viral_clipper.errors import ClipperError, InvalidSourceError, NoClipsError, RenderError
from viral_clipper.ingest.ffprobe import ensure_ffmpeg
from viral_clipper.ingest.source import resolve_source
from viral_clipper.metadata import llm as llm_mod
from viral_clipper.metadata.outputs import find_clip, read_result, write_outputs
from viral_clipper.metadata.templates import TemplateEngine
from viral_clipper.models import (
    ALL_PLATFORMS,
    AnalysisResult,
    AnalysisSummary,
    Candidate,
    ClipMetadata,
    ClipRecord,
    ClipVideoResult,
    Platform,
    SentenceSummary,
    StoryMap,
    StoryOverview,
    StorySentence,
)
from viral_clipper.progress import ProgressFn, StageProgress
from viral_clipper.render.clip import RenderedClip, render_clip
from viral_clipper.scoring.candidates import Window
from viral_clipper.scoring.edits import WordBounds, merge_segments, score_stories, unit_segments
from viral_clipper.scoring.scorer import Scorer, score_moments
from viral_clipper.scoring.signals import SignalContext
from viral_clipper.scoring.stories import Unit, pick_payoffs

log = logging.getLogger(__name__)


@dataclass
class ClipRequest:
    source: str
    niche: str = "generic"
    num_clips: int = 10
    min_len: float = 30.0
    max_len: float = 70.0
    platforms: list[Platform] = field(default_factory=lambda: list(ALL_PLATFORMS))
    output_dir: str | None = None


def _with_output_dir(cfg: Config, output_dir: str | None) -> Config:
    if not output_dir:
        return cfg
    cfg = cfg.model_copy(deep=True)
    cfg.paths.output_dir = output_dir
    return cfg


def run_analyze(source: str, cfg: Config, progress: ProgressFn | None = None, force: bool = False) -> AnalysisSummary:
    ensure_ffmpeg()
    stages = StageProgress({"ingest": 1.0, "analyze": 8.0}, progress)
    video, work_dir = resolve_source(source, cfg, stages.sub("ingest"))
    stages.report("ingest", 1.0, f"Source ready: {video.title}")
    result = analyze(video, work_dir, cfg, stages.sub("analyze"), force=force)
    return summarize(result, cache_path(work_dir))


def summarize(result, cache: Path) -> AnalysisSummary:
    def to_1hz(name: str) -> list[float]:
        curve = result.curves.get(name)
        if curve is None or not curve.values:
            return []
        step = max(1, int(curve.rate_hz))
        vals = curve.values
        return [round(sum(vals[i : i + step]) / len(vals[i : i + step]), 3) for i in range(0, len(vals), step)]

    peaks = sorted(result.events, key=lambda e: e.strength, reverse=True)[:25]
    return AnalysisSummary(
        video=result.video,
        transcript_backend=result.transcript.backend,
        sentences=[
            SentenceSummary(text=s.text, start=round(s.start, 2), end=round(s.end, 2))
            for s in result.transcript.sentences
        ],
        scene_cuts=[round(c, 2) for c in result.scene_cuts],
        audio_peaks=sorted(peaks, key=lambda e: e.time),
        energy_curve_1hz=to_1hz("audio_rms_z"),
        motion_curve_1hz=to_1hz("motion"),
        cache_path=str(cache),
    )


def is_commentated(result: AnalysisResult, min_wpm: float) -> bool:
    """Story edits are built from what people say. Raw gameplay with a handful of stray words has
    no story to follow, so it gets continuous action windows: jump cuts in wordless footage just
    look like skipped frames."""
    minutes = max(result.video.duration / 60.0, 1e-6)
    return len(result.transcript.words) / minutes >= min_wpm


def select_clips(result: AnalysisResult, profile: Profile, req: ClipRequest, cfg: Config) -> list[Candidate]:
    """Story mode (default): one complete story per clip, filler jump-cut out. Window mode: the old
    single contiguous window."""
    if cfg.clip.mode == "story" and is_commentated(result, cfg.clip.min_speech_wpm):
        selected, _edits, _model = score_stories(result, profile, req.num_clips, req.min_len, req.max_len, cfg.clip)
        return selected
    selected, _all = score_moments(
        result,
        profile,
        req.num_clips,
        req.min_len,
        req.max_len,
        cfg.clip.pre_roll_s,
        cfg.clip.post_roll_s,
        cfg.clip.min_gap_s,
        cfg.clip.min_context,
    )
    return selected


def run_score(req: ClipRequest, cfg: Config, progress: ProgressFn | None = None) -> list[Candidate]:
    ensure_ffmpeg()
    cfg = _with_output_dir(cfg, req.output_dir)
    profile = load_profile(req.niche)
    stages = StageProgress({"ingest": 1.0, "analyze": 8.0, "score": 0.5}, progress)
    video, work_dir = resolve_source(req.source, cfg, stages.sub("ingest"))
    result = analyze(video, work_dir, cfg, stages.sub("analyze"))
    stages.report("score", 0.1, "Finding stories and scoring moments")
    selected = select_clips(result, profile, req, cfg)
    stages.report("score", 1.0, f"{len(selected)} moments selected")
    return selected


def run_clip_video(req: ClipRequest, cfg: Config, progress: ProgressFn | None = None) -> ClipVideoResult:
    ensure_ffmpeg()
    cfg = _with_output_dir(cfg, req.output_dir)
    profile = load_profile(req.niche)
    timings: dict[str, float] = {}
    warnings: list[str] = []
    stages = StageProgress(
        {
            "ingest": 1.0,
            "analyze": 8.0,
            "score": 0.3,
            "render": 3.0 * max(1, req.num_clips),
            "metadata": 0.5,
            "write": 0.1,
        },
        progress,
    )

    t0 = time.perf_counter()
    video, work_dir = resolve_source(req.source, cfg, stages.sub("ingest"))
    timings["ingest"] = time.perf_counter() - t0
    stages.report("ingest", 1.0, f"Source ready: {video.title}")

    t0 = time.perf_counter()
    result = analyze(video, work_dir, cfg, stages.sub("analyze"))
    timings["analyze"] = time.perf_counter() - t0
    if result.transcript.is_empty:
        warnings.append(
            "No speech was transcribed; clips were chosen from audio/motion/scene signals only and have no captions."
        )

    t0 = time.perf_counter()
    stages.report("score", 0.1, "Finding stories and scoring moments")
    selected = select_clips(result, profile, req, cfg)
    timings["score"] = time.perf_counter() - t0
    if not selected:
        raise NoClipsError(
            f"No {req.min_len:.0f}-{req.max_len:.0f}s moments could be cut from {video.title!r} "
            f"({video.duration:.0f}s long)."
        )
    if len(selected) < req.num_clips:
        warnings.append(
            f"Only {len(selected)} non-overlapping clips fit in a {video.duration:.0f}s video "
            f"(asked for {req.num_clips})."
        )
    stages.report("score", 1.0, f"{len(selected)} moments selected")

    engine = TemplateEngine(profile, video.title, video.credit)
    use_llm = llm_mod.llm_enabled(cfg)
    platforms = req.platforms or list(ALL_PLATFORMS)
    clips: list[ClipRecord] = []
    t_render = 0.0
    t_meta = 0.0
    for i, cand in enumerate(selected, start=1):
        t0 = time.perf_counter()
        draft_hook, draft = engine.bundle(cand, i, platforms)
        hook, meta, virality = draft_hook, draft, None
        if use_llm:
            hook, meta, virality = llm_mod.refine_with_llm(
                cand, video.title, profile, draft_hook, draft, platforms, cfg
            )
        score = cand.score
        if virality is not None and cfg.llm.fusion_weight > 0:
            w = cfg.llm.fusion_weight
            score = round((1 - w) * cand.score + w * virality.overall, 1)
            cand.reasons.append(f"Claude: {virality.reason}")
        t_meta += time.perf_counter() - t0

        t0 = time.perf_counter()
        sub = stages.sub("render")
        try:
            rendered = render_clip(
                result,
                cand,
                i,
                hook,
                work_dir,
                cfg,
                progress=lambda f, m, i=i, sub=sub: sub((i - 1 + f) / len(selected), m),
            )
        except ClipperError as exc:
            # One bad clip must not throw away the other nine; report it and keep going.
            log.error("clip %02d (%.1f-%.1f s) failed: %s", i, cand.start, cand.end, exc)
            warnings.append(f"clip_{i:02d} ({cand.start:.0f}-{cand.end:.0f}s) failed to render: {exc}")
            t_render += time.perf_counter() - t0
            continue
        t_render += time.perf_counter() - t0
        clips.append(_record(i, cand, rendered, score, hook, meta))
    timings["render"] = t_render
    timings["metadata"] = t_meta
    if not clips:
        raise RenderError(f"Every clip failed to render for {video.title!r}; see the warnings and the log.")
    stages.report("metadata", 1.0, "Metadata ready" + (" (Claude)" if use_llm else " (templates)"))

    out = ClipVideoResult(
        video_title=video.title,
        source=video.source_url or video.path,
        credit=video.credit,
        output_dir=str(work_dir),
        clips_json=str(work_dir / "clips.json"),
        clips_csv=str(work_dir / "clips.csv"),
        clips=clips,
        warnings=warnings,
        timings_s={k: round(v, 1) for k, v in timings.items()},
    )
    write_outputs(out)
    stages.report("write", 1.0, f"Saved {len(clips)} clips to {work_dir}")
    return out


def _record(index: int, cand: Candidate, rendered: RenderedClip, score: float, hook: str, meta) -> ClipRecord:
    return ClipRecord(
        index=index,
        path=str(rendered.path),
        thumbnail_path=str(rendered.thumbnail),
        srt_path=str(rendered.srt),
        start=cand.start,
        end=cand.end,
        duration=round(cand.duration, 2),
        score=score,
        reasons=cand.reasons,
        transcript_text=cand.transcript_text,
        hook=hook,
        hook_pattern=cand.hook_pattern,
        metadata=meta,
        features=cand.features,
        thumbnail_time=rendered.thumbnail_time,
        thumbnail_alternatives=[str(a) for a in rendered.thumbnail_alternatives],
        segments=cand.segments,
        story=cand.story,
    )


def run_generate_metadata(clip_path: str, platform: Platform, niche: str | None, cfg: Config) -> ClipMetadata:
    """Regenerate metadata for one existing clip (templates, refined by Claude when available)."""
    result, clip, _json = find_clip(Path(clip_path), cfg.output_root)
    profile = load_profile(niche or cfg.default_niche)
    cand = Candidate(
        start=clip.start,
        end=clip.end,
        score=clip.score,
        peak_time=clip.start + clip.duration * 0.7,
        features=clip.features,
        contributions=[],
        reasons=clip.reasons,
        transcript_text=clip.transcript_text,
        hook_pattern=clip.hook_pattern,
    )
    engine = TemplateEngine(profile, result.video_title, result.credit)
    hook, draft = engine.bundle(cand, clip.index, [platform])
    if llm_mod.llm_enabled(cfg):
        hook, draft, _v = llm_mod.refine_with_llm(cand, result.video_title, profile, hook, draft, [platform], cfg)
    return draft[platform]


def parse_timestamp(value: str | float | int) -> float:
    """Accepts seconds (80, "80", "80.5") or clock strings ("1:20", "17:42", "1:02:03")."""
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if ":" not in text:
        return float(text)
    parts = [float(p) for p in text.split(":")]
    if len(parts) > 3:
        raise InvalidSourceError(f"Bad timestamp {value!r}; use seconds or mm:ss / h:mm:ss.")
    total = 0.0
    for part in parts:
        total = total * 60 + part
    return total


def run_story_map(source: str, niche: str, cfg: Config, progress: ProgressFn | None = None) -> StoryMap:
    """Every story in the video with numbered sentences, beat roles and the automatic edits."""
    ensure_ffmpeg()
    profile = load_profile(niche)
    stages = StageProgress({"ingest": 1.0, "analyze": 8.0, "stories": 0.5}, progress)
    video, work_dir = resolve_source(source, cfg, stages.sub("ingest"))
    result = analyze(video, work_dir, cfg, stages.sub("analyze"))
    if result.transcript.is_empty:
        raise NoClipsError("No speech was transcribed, so there are no stories to map; use clip_video instead.")
    _sel, edits, model = score_stories(
        result, profile, cfg.clip.num_clips, cfg.clip.min_len, cfg.clip.max_len, cfg.clip
    )
    stories: list[StoryOverview] = []
    for story in model.stories:
        payoffs = {story.units[p].index for p in pick_payoffs(story)}
        sentences = []
        for u in story.units:
            if u.is_ad:
                role = "sponsor"
            elif u.cue:
                role = "transition"
            elif u.index in payoffs:
                role = "payoff"
            elif u.kind == "action":
                role = "action"
            elif u.payoff_words >= 0.5:
                role = "payoff"
            elif u.stakes >= 0.5:
                role = "stakes"
            elif u.is_filler:
                role = "filler"
            else:
                role = "body"
            sentences.append(
                StorySentence(
                    id=u.sentence_index,
                    start=round(u.start, 2),
                    end=round(u.end, 2),
                    text=u.text or "[no speech: action]",
                    role=role,
                )
            )
        mine = [c for c in edits if c.story and c.story.story_index == story.index]
        premise = next((c.story.premise for c in mine if c.story and c.story.premise), "")
        names = next((c.story.names for c in mine if c.story and c.story.names), [])
        stories.append(
            StoryOverview(
                index=story.index,
                start=round(story.start, 2),
                end=round(story.end, 2),
                premise=premise,
                names=names,
                sentences=sentences,
                proposed_edits=[c.segments for c in mine],
                proposed_scores=[c.score for c in mine],
            )
        )
    stages.report("stories", 1.0, f"{len(stories)} stories")
    return StoryMap(video_title=video.title, source=video.source_url or video.path, stories=stories)


def _segments_from_sentences(result: AnalysisResult, ids: list[int], cfg: Config) -> list[tuple[float, float]]:
    """Sentence ids → tightened source ranges (long pauses inside a sentence are cut too)."""
    sentences = result.transcript.sentences
    bad = [i for i in ids if not 0 <= i < len(sentences)]
    if bad:
        raise InvalidSourceError(f"Unknown sentence ids {bad}; story_map lists ids 0-{len(sentences) - 1}.")
    ctx = SignalContext.from_analysis(result)
    bounds = WordBounds(ctx)
    raw: list[tuple[float, float]] = []
    for i in sorted(set(ids)):
        s = sentences[i]
        unit = Unit(index=i, start=s.start, end=s.end, kind="speech", text=s.text, words=list(s.words))
        raw += unit_segments(unit, ctx, cfg.clip.max_pause_s, bounds=bounds)
    return merge_segments(raw, cfg.clip.max_pause_s, result.video.duration)


def run_render_edit(
    source: str,
    cfg: Config,
    segments: list[tuple[str | float, str | float]] | None = None,
    sentence_ids: list[int] | None = None,
    niche: str = "generic",
    hook: str | None = None,
    platforms: list[Platform] | None = None,
    output_dir: str | None = None,
    progress: ProgressFn | None = None,
    manual_note: str = "manual edit",
) -> ClipRecord:
    """Render any edit list (source ranges and/or transcript sentence ids, played in time order) with the
    same captions, reframe, hook card and loudness as clip_video, appended as the next clip number."""
    ensure_ffmpeg()
    cfg = _with_output_dir(cfg, output_dir)
    profile = load_profile(niche)
    if not segments and not sentence_ids:
        raise InvalidSourceError("Give segments (start/end pairs) or sentence_ids from story_map.")
    stages = StageProgress({"ingest": 1.0, "analyze": 8.0, "render": 3.0, "write": 0.1}, progress)
    video, work_dir = resolve_source(source, cfg, stages.sub("ingest"))
    stages.report("ingest", 1.0, f"Source ready: {video.title}")
    result = analyze(video, work_dir, cfg, stages.sub("analyze"))

    parts: list[tuple[float, float]] = []
    for a, b in segments or []:
        t0, t1 = parse_timestamp(a), parse_timestamp(b)
        if t1 - t0 < 0.3:
            raise InvalidSourceError(f"Segment {a}-{b} is shorter than 0.3 s.")
        if t1 > video.duration + 0.5:
            raise InvalidSourceError(f"{t1:.0f}s is past the end of the video ({video.duration:.0f}s).")
        parts.append((t0, min(t1, video.duration)))
    if sentence_ids:
        parts += _segments_from_sentences(result, sentence_ids, cfg)
    parts = merge_segments(parts, 0.0, video.duration)
    if sum(b - a for a, b in parts) < 3:
        raise InvalidSourceError("An edit must be at least 3 seconds long.")

    scorer = Scorer(result, profile)
    window = Window(start=parts[0][0], end=parts[-1][1], on_sentences=bool(sentence_ids), segments=tuple(parts))
    cand = scorer.score_window(window)
    if len(parts) == 1:
        cand.segments = []
    span = f"{parts[0][0]:.0f}-{parts[-1][1]:.0f}s" + (f" in {len(parts)} pieces" if len(parts) > 1 else "")
    cand.reasons = [f"{manual_note} {span}", *cand.reasons]

    existing = read_result(work_dir / "clips.json") if (work_dir / "clips.json").exists() else None
    index = (max((c.index for c in existing.clips), default=0) + 1) if existing else 1
    plats = platforms or list(ALL_PLATFORMS)
    engine = TemplateEngine(profile, video.title, video.credit)
    # A hand-written hook is the clip's premise: it leads the descriptions too, not just the card.
    draft_hook, meta = engine.bundle(cand, index, plats, hook=hook.strip() if hook else None)
    hook_text = draft_hook
    if llm_mod.llm_enabled(cfg) and not hook:
        hook_text, meta, _v = llm_mod.refine_with_llm(cand, video.title, profile, draft_hook, meta, plats, cfg)

    rendered = render_clip(result, cand, index, hook_text, work_dir, cfg, progress=stages.sub("render"))
    record = _record(index, cand, rendered, cand.score, hook_text, meta)
    if existing is None:
        existing = ClipVideoResult(
            video_title=video.title,
            source=video.source_url or video.path,
            credit=video.credit,
            output_dir=str(work_dir),
            clips_json=str(work_dir / "clips.json"),
            clips_csv=str(work_dir / "clips.csv"),
            clips=[],
        )
    existing.clips.append(record)
    write_outputs(existing)
    stages.report("write", 1.0, f"Saved {rendered.path.name}")
    return record


def run_cut_clip(
    source: str,
    start: str | float,
    end: str | float | None,
    duration: str | float | None,
    cfg: Config,
    niche: str = "generic",
    hook: str | None = None,
    platforms: list[Platform] | None = None,
    output_dir: str | None = None,
    progress: ProgressFn | None = None,
) -> ClipRecord:
    """Cut one clip from an exact time range; a one-segment render_edit."""
    t_start = parse_timestamp(start)
    if end is None and duration is None:
        raise InvalidSourceError("Give either end or duration for the cut.")
    t_end = parse_timestamp(end) if end is not None else t_start + parse_timestamp(duration)  # type: ignore[arg-type]
    if t_end - t_start < 3:
        raise InvalidSourceError("A cut must be at least 3 seconds long.")
    return run_render_edit(
        source,
        cfg,
        segments=[(t_start, t_end)],
        niche=niche,
        hook=hook,
        platforms=platforms,
        output_dir=output_dir,
        progress=progress,
        manual_note="manual cut",
    )
