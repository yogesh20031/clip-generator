"""End-to-end orchestration shared by the MCP server and the CLI."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from viral_clipper.analysis.analyze import analyze, cache_path
from viral_clipper.config import Config, load_profile
from viral_clipper.errors import ClipperError, InvalidSourceError, NoClipsError, RenderError
from viral_clipper.ingest.ffprobe import ensure_ffmpeg
from viral_clipper.ingest.source import resolve_source
from viral_clipper.metadata import llm as llm_mod
from viral_clipper.metadata.outputs import find_clip, read_result, write_outputs
from viral_clipper.metadata.templates import TemplateEngine
from viral_clipper.models import (
    ALL_PLATFORMS,
    AnalysisSummary,
    Candidate,
    ClipMetadata,
    ClipRecord,
    ClipVideoResult,
    Platform,
    SentenceSummary,
)
from viral_clipper.progress import ProgressFn, StageProgress
from viral_clipper.render.clip import render_clip
from viral_clipper.scoring.candidates import Window
from viral_clipper.scoring.scorer import Scorer, score_moments

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


def run_score(req: ClipRequest, cfg: Config, progress: ProgressFn | None = None) -> list[Candidate]:
    ensure_ffmpeg()
    cfg = _with_output_dir(cfg, req.output_dir)
    profile = load_profile(req.niche)
    stages = StageProgress({"ingest": 1.0, "analyze": 8.0, "score": 0.5}, progress)
    video, work_dir = resolve_source(req.source, cfg, stages.sub("ingest"))
    result = analyze(video, work_dir, cfg, stages.sub("analyze"))
    stages.report("score", 0.1, "Scoring candidate moments")
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
    stages.report("score", 0.1, "Scoring candidate moments")
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

    engine = TemplateEngine(profile)
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
        clips.append(
            ClipRecord(
                index=i,
                path=str(rendered.path),
                thumbnail_path=str(rendered.thumbnail),
                srt_path=str(rendered.srt),
                start=cand.start,
                end=cand.end,
                duration=round(cand.end - cand.start, 2),
                score=score,
                reasons=cand.reasons,
                transcript_text=cand.transcript_text,
                hook=hook,
                hook_pattern=cand.hook_pattern,
                metadata=meta,
                features=cand.features,
                thumbnail_time=rendered.thumbnail_time,
                thumbnail_alternatives=[str(a) for a in rendered.thumbnail_alternatives],
            )
        )
    timings["render"] = t_render
    timings["metadata"] = t_meta
    if not clips:
        raise RenderError(f"Every clip failed to render for {video.title!r}; see the warnings and the log.")
    stages.report("metadata", 1.0, "Metadata ready" + (" (Claude)" if use_llm else " (templates)"))

    out = ClipVideoResult(
        video_title=video.title,
        source=video.source_url or video.path,
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
    engine = TemplateEngine(profile)
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
    """Cut one clip from an exact time range, with the same captions, hook, reframe and loudness as
    clip_video, and append it to the video's clips.json / clips.csv as the next clip number."""
    ensure_ffmpeg()
    cfg = _with_output_dir(cfg, output_dir)
    profile = load_profile(niche)
    t_start = parse_timestamp(start)
    if end is None and duration is None:
        raise InvalidSourceError("Give either end or duration for the cut.")
    t_end = parse_timestamp(end) if end is not None else t_start + parse_timestamp(duration)  # type: ignore[arg-type]
    if t_end - t_start < 3:
        raise InvalidSourceError("A cut must be at least 3 seconds long.")

    stages = StageProgress({"ingest": 1.0, "analyze": 8.0, "render": 3.0, "write": 0.1}, progress)
    video, work_dir = resolve_source(source, cfg, stages.sub("ingest"))
    if t_end > video.duration + 0.5:
        raise InvalidSourceError(f"{t_end:.0f}s is past the end of the video ({video.duration:.0f}s).")
    t_end = min(t_end, video.duration)
    stages.report("ingest", 1.0, f"Source ready: {video.title}")
    result = analyze(video, work_dir, cfg, stages.sub("analyze"))

    scorer = Scorer(result, profile)
    cand = scorer.score_window(Window(start=t_start, end=t_end, on_sentences=False))
    cand.reasons = [f"manual cut {t_start:.0f}-{t_end:.0f}s", *cand.reasons]

    existing = read_result(work_dir / "clips.json") if (work_dir / "clips.json").exists() else None
    index = (max((c.index for c in existing.clips), default=0) + 1) if existing else 1
    plats = platforms or list(ALL_PLATFORMS)
    engine = TemplateEngine(profile)
    draft_hook, meta = engine.bundle(cand, index, plats)
    hook_text = hook.strip() if hook else draft_hook
    if hook:
        meta = {p: m.model_copy(update={"hook": hook_text}) for p, m in meta.items()}
    if llm_mod.llm_enabled(cfg) and not hook:
        hook_text, meta, _v = llm_mod.refine_with_llm(cand, video.title, profile, draft_hook, meta, plats, cfg)

    rendered = render_clip(result, cand, index, hook_text, work_dir, cfg, progress=stages.sub("render"))
    record = ClipRecord(
        index=index,
        path=str(rendered.path),
        thumbnail_path=str(rendered.thumbnail),
        srt_path=str(rendered.srt),
        start=cand.start,
        end=cand.end,
        duration=round(cand.end - cand.start, 2),
        score=cand.score,
        reasons=cand.reasons,
        transcript_text=cand.transcript_text,
        hook=hook_text,
        hook_pattern=cand.hook_pattern,
        metadata=meta,
        features=cand.features,
        thumbnail_time=rendered.thumbnail_time,
        thumbnail_alternatives=[str(a) for a in rendered.thumbnail_alternatives],
    )
    if existing is None:
        existing = ClipVideoResult(
            video_title=video.title,
            source=video.source_url or video.path,
            output_dir=str(work_dir),
            clips_json=str(work_dir / "clips.json"),
            clips_csv=str(work_dir / "clips.csv"),
            clips=[],
        )
    existing.clips.append(record)
    write_outputs(existing)
    stages.report("write", 1.0, f"Saved {rendered.path.name}")
    return record
