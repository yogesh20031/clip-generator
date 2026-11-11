"""The MCP server. Tools are thin wrappers around pipeline.py; heavy work runs on a worker thread
so progress notifications keep flowing."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from viral_clipper import pipeline
from viral_clipper.config import Config, get_config, list_profiles
from viral_clipper.errors import ClipperError
from viral_clipper.ingest.ffprobe import ensure_ffmpeg
from viral_clipper.log import setup_logging
from viral_clipper.metadata import outputs
from viral_clipper.models import (
    ALL_PLATFORMS,
    AnalysisSummary,
    Candidate,
    ClipMetadata,
    ClipRecord,
    ClipVideoResult,
    OutputEntry,
    Platform,
)

log = logging.getLogger(__name__)

INSTRUCTIONS = """viral-clipper cuts long videos (YouTube URL or local file) into vertical 9:16 short clips.
Typical flow: analyze_video -> score_moments (optional preview) -> clip_video; cut_clip renders one exact
range. Clips, clips.json and clips.csv land in <output_dir>/<video-title>/ (default ~/Desktop/viral-clipper).
Niches: gta6, mrbeast, generic. Metadata is template-generated unless Anthropic credentials are configured;
you can always rewrite copy yourself and persist it with set_clip_metadata."""

mcp = MCPServer("viral-clipper", instructions=INSTRUCTIONS)

_config_override: Config | None = None


def set_config(cfg: Config | None) -> None:
    """Tests inject a config here; production reads config.yaml."""
    global _config_override
    _config_override = cfg


def _cfg() -> Config:
    return _config_override or get_config()


async def _run[T](ctx: Context, fn: Callable[..., T], *args, **kwargs) -> T:
    """Run blocking pipeline code off the event loop, bridging progress back to MCP."""

    def progress(fraction: float, message: str) -> None:
        try:
            anyio.from_thread.run(ctx.report_progress, round(fraction * 100, 2), 100.0, message)
        except Exception:  # client without progress support, or notification race on shutdown
            log.debug("progress notification dropped: %s", message)

    try:
        return await anyio.to_thread.run_sync(partial(fn, *args, **kwargs, progress=progress))
    except ClipperError as exc:
        raise ToolError(exc.user_message()) from exc
    except Exception as exc:
        log.exception("unexpected failure in %s", getattr(fn, "__name__", fn))
        raise ToolError(f"{type(exc).__name__}: {exc}. See logs/viral-clipper.log for the traceback.") from exc


def _platforms(names: list[str] | None) -> list[Platform]:
    if not names:
        return list(ALL_PLATFORMS)
    try:
        return [Platform(n) for n in names]
    except ValueError as exc:
        raise ToolError(f"Unknown platform {exc}. Use: {', '.join(p.value for p in ALL_PLATFORMS)}") from exc


@mcp.tool()
async def clip_video(
    source: str,
    niche: str = "generic",
    num_clips: int = 10,
    min_len: int = 30,
    max_len: int = 70,
    platforms: list[str] | None = None,
    output_dir: str | None = None,
    ctx: Context = None,  # type: ignore[assignment]
) -> ClipVideoResult:
    """Find the most viral-worthy moments in a video and cut them into captioned 9:16 clips.

    source: a YouTube URL or a local mp4/mov/mkv path. niche: gta6 | mrbeast | generic (a profile in
    profiles/). Clips run 30-70 s by default and are saved next to the source video in
    <output_dir>/<video-title>/ as clip_NN.mp4 (1080x1920, word-by-word captions, hook overlay, -14 LUFS)
    plus thumbnails, clips.json and clips.csv with score, timestamps, title, hashtags, description and hook
    for each platform. Long videos take minutes: transcription dominates.
    """
    if niche not in list_profiles():
        raise ToolError(f"Unknown niche {niche!r}. Available: {', '.join(list_profiles())}.")
    if not (5 <= min_len < max_len <= 180):
        raise ToolError("Expected 5 <= min_len < max_len <= 180 seconds.")
    req = pipeline.ClipRequest(
        source=source,
        niche=niche,
        num_clips=max(1, num_clips),
        min_len=float(min_len),
        max_len=float(max_len),
        platforms=_platforms(platforms),
        output_dir=output_dir,
    )
    return await _run(ctx, pipeline.run_clip_video, req, _cfg())


@mcp.tool()
async def cut_clip(
    source: str,
    start: str,
    end: str | None = None,
    duration: str | None = None,
    niche: str = "generic",
    hook: str | None = None,
    platforms: list[str] | None = None,
    output_dir: str | None = None,
    ctx: Context = None,  # type: ignore[assignment]
) -> ClipRecord:
    """Cut ONE clip from an exact time range you choose (start plus end or duration, as seconds or
    mm:ss), with the same 9:16 reframe, word captions, hook card, loudness and metadata as clip_video.
    It is appended to that video's clips.json/clips.csv as the next clip number. Pass hook to use your
    own on-screen hook text."""
    if niche not in list_profiles():
        raise ToolError(f"Unknown niche {niche!r}. Available: {', '.join(list_profiles())}.")
    return await _run(
        ctx,
        pipeline.run_cut_clip,
        source,
        start,
        end,
        duration,
        _cfg(),
        niche=niche,
        hook=hook,
        platforms=_platforms(platforms),
        output_dir=output_dir,
    )


@mcp.tool()
async def analyze_video(source: str, force: bool = False, ctx: Context = None) -> AnalysisSummary:  # type: ignore[assignment]
    """Transcribe and analyze a video: sentences with timestamps, scene cuts, audio peaks, and 1 Hz
    energy/motion curves. Results are cached next to the video; force=true recomputes."""
    return await _run(ctx, pipeline.run_analyze, source, _cfg(), force=force)


@mcp.tool()
async def score_moments(
    source: str,
    niche: str = "generic",
    num_clips: int = 10,
    min_len: int = 30,
    max_len: int = 70,
    ctx: Context = None,  # type: ignore[assignment]
) -> list[Candidate]:
    """Rank candidate moments for a niche without rendering anything. Each candidate has start/end,
    a 0-100 score, the per-signal contributions and plain-language reasons."""
    if niche not in list_profiles():
        raise ToolError(f"Unknown niche {niche!r}. Available: {', '.join(list_profiles())}.")
    req = pipeline.ClipRequest(
        source=source, niche=niche, num_clips=max(1, num_clips), min_len=float(min_len), max_len=float(max_len)
    )
    return await _run(ctx, pipeline.run_score, req, _cfg())


@mcp.tool()
async def generate_metadata(clip_path: str, platform: str = "youtube_shorts", niche: str | None = None) -> ClipMetadata:
    """Generate title, description, hashtags and hook for an existing clip on one platform
    (youtube_shorts | tiktok | instagram_reels | facebook_reels). Does not persist; use
    set_clip_metadata to save edited copy."""
    try:
        return pipeline.run_generate_metadata(clip_path, _platforms([platform])[0], niche, _cfg())
    except ClipperError as exc:
        raise ToolError(exc.user_message()) from exc


@mcp.tool()
async def set_clip_metadata(
    clip_path: str, platform: str, title: str, description: str, hashtags: list[str], hook: str = ""
) -> str:
    """Save your own title/description/hashtags/hook for a clip into clips.json and clips.csv.
    Use this to replace template copy with better writing."""
    plat = _platforms([platform])[0]
    meta = ClipMetadata(platform=plat, title=title, description=description, hashtags=hashtags, hook=hook)
    try:
        clip = outputs.update_clip_metadata(__import__("pathlib").Path(clip_path), plat, meta, _cfg().output_root)
    except ClipperError as exc:
        raise ToolError(exc.user_message()) from exc
    return f"Saved {plat.value} metadata for clip {clip.index} ({clip.path})."


@mcp.tool()
async def list_outputs(output_dir: str | None = None) -> list[OutputEntry]:
    """List every processed video and its saved clips with their metadata."""
    cfg = _cfg()
    root = pipeline._with_output_dir(cfg, output_dir).output_root
    return outputs.list_outputs(root)


def main() -> None:
    cfg = get_config()
    setup_logging(cfg.log_dir, cfg.log_level)
    try:
        ensure_ffmpeg()
    except ClipperError as exc:  # keep serving so the model gets a clear error from each tool
        log.error("%s", exc.user_message())
    log.info("viral-clipper MCP server starting (output: %s)", cfg.output_root)
    mcp.run()


if __name__ == "__main__":
    main()
