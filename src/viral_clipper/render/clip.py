"""Cut, reframe, caption and loudness-normalize one clip with FFmpeg."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from viral_clipper.config import Config
from viral_clipper.models import AnalysisResult, Candidate
from viral_clipper.progress import ProgressFn
from viral_clipper.render import captions as cap
from viral_clipper.render.crop import plan_crop
from viral_clipper.render.ffmpeg import (
    audio_concat_filter,
    loudnorm_filter,
    measure_loudness,
    run_ffmpeg,
    segment_inputs,
)
from viral_clipper.render.hook_overlay import render_hook
from viral_clipper.render.thumbnail import pick_thumbnail

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderedClip:
    path: Path
    thumbnail: Path
    srt: Path
    ass: Path
    thumbnail_time: float = 0.0
    thumbnail_alternatives: tuple[Path, ...] = ()


def to_clip_time(parts: list[tuple[float, float]], durations: list[float], t: float) -> float:
    """Source seconds → seconds into the rendered clip (nearest kept moment if t was cut out)."""
    offset = 0.0
    best = (float("inf"), 0.0)
    for (a, _b), dur in zip(parts, durations, strict=True):
        if a <= t <= a + dur:
            return offset + (t - a)
        dist = min(abs(t - a), abs(t - (a + dur)))
        if dist < best[0]:
            best = (dist, offset + (0.0 if t < a else dur))
        offset += dur
    return best[1]


def clip_name(index: int) -> str:
    return f"clip_{index:02d}"


def render_clip(
    analysis: AnalysisResult,
    cand: Candidate,
    index: int,
    hook_text: str,
    work_dir: Path,
    cfg: Config,
    progress: ProgressFn | None = None,
) -> RenderedClip:
    name = clip_name(index)
    out_path = work_dir / f"{name}.mp4"
    thumb_path = work_dir / "thumbnails" / f"{name}.jpg"
    srt_path = work_dir / "captions" / f"{name}.srt"
    ass_path = work_dir / "captions" / f"{name}.ass"
    tmp = work_dir / ".tmp" / name
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    srt_path.parent.mkdir(parents=True, exist_ok=True)

    size = (cfg.clip.width, cfg.clip.height)
    src = Path(analysis.video.path)
    fps = cfg.clip.fps
    # Frame-exact segment lengths keep audio and video in lock-step across every jump cut.
    parts: list[tuple[float, float]] = []
    durations: list[float] = []
    for seg in cand.parts:
        frames = max(1, round((seg.end - seg.start) * fps))
        dur = frames / fps
        parts.append((seg.start, seg.start + dur))
        durations.append(dur)
    duration = sum(durations)
    n = len(parts)

    def report(frac: float, msg: str) -> None:
        if progress:
            progress(frac, f"{name}: {msg}")

    # 1. Captions + hook overlays (Pillow), on the clip's own timeline.
    report(0.02, "rendering captions")
    words_by_part = [analysis.transcript.words_between(a, b) for a, b in parts]
    words, breaks = cap.clip_timeline_words(words_by_part, parts, durations)
    inputs: list[str] = segment_inputs(src, parts)
    overlay_filters: list[str] = []
    input_index = n
    if cfg.captions.enabled and words:
        items, lines = cap.build_caption_sequence(
            words, 0.0, duration, size, cfg.captions, cfg.font_path, tmp / "captions", breaks
        )
        concat = cap.write_concat_list(items, tmp / "captions.txt")
        cap.write_subtitle_files(lines, 0.0, srt_path, ass_path)
        inputs += ["-f", "concat", "-safe", "0", "-i", str(concat)]
        overlay_filters.append(f"[{input_index}:v]")
        input_index += 1
    else:
        srt_path.write_text("", encoding="utf-8")
        ass_path.write_text("", encoding="utf-8")
    if cfg.captions.hook_enabled and hook_text.strip():
        hook_png = render_hook(hook_text, size, cfg.captions, cfg.font_path, tmp / "hook.png")
        # A premise card ("Khalid vs Ronaldo for $1M") carries the context, so it stays up longer.
        hold = (
            cfg.captions.premise_duration_s
            if cand.premise and hook_text == cand.premise
            else cfg.captions.hook_duration_s
        )
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{min(hold, duration):.2f}", "-i", str(hook_png)]
        overlay_filters.append(f"[{input_index}:v]")
        input_index += 1

    # 2. Reframe plan per segment (face -> motion -> centre); each input's t starts at 0.
    report(0.10, "planning the crop")
    chain: list[str] = []
    for i, (a, b) in enumerate(parts):
        plan = plan_crop(analysis, a, b, cfg.clip.width, cfg.clip.height, cfg.face_model_path)
        if plan.axis == "x":
            crop = f"crop={plan.crop_w}:{plan.crop_h}:x='{plan.expression()}':y=0"
        else:
            crop = f"crop={plan.crop_w}:{plan.crop_h}:x=0:y='{plan.expression()}'"
        chain.append(
            f"[{i}:v]{crop},scale={cfg.clip.width}:{cfg.clip.height}:flags=lanczos,fps={fps},setsar=1,"
            f"format=yuv420p,tpad=stop_mode=clone:stop_duration=0.2,trim=duration={durations[i]:.4f},"
            f"setpts=PTS-STARTPTS[v{i}s]"
        )
    chain.append(audio_concat_filter(n, durations))
    if n == 1:
        chain.append("[v0s]null[vcat]")
    else:
        chain.append("".join(f"[v{i}s]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vcat]")

    # 3. Loudness pass 1 over the joined audio.
    report(0.15, "measuring loudness")
    measured = measure_loudness(src, parts, durations, cfg.clip)

    # 4. Pass 2: the real render.
    last = "[vcat]"
    for i, label in enumerate(overlay_filters):
        out = f"[o{i + 1}]"
        chain.append(f"{last}{label}overlay=0:0:eof_action=pass:format=auto{out}")
        last = out
    chain.append(f"{last}format=yuv420p[vout]")
    chain.append(f"[acat]{loudnorm_filter(measured, cfg.clip)},aresample=48000[aout]")
    args = [
        *inputs,
        "-filter_complex",
        ";".join(chain),
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        cfg.clip.preset,
        "-crf",
        str(cfg.clip.crf),
        "-profile:v",
        "high",
        "-c:a",
        "aac",
        "-b:a",
        cfg.clip.audio_bitrate,
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        "-t",
        f"{duration:.3f}",
        str(out_path),
    ]
    run_ffmpeg(args, duration, lambda f, _m: report(0.2 + 0.75 * f, "encoding"), what=name)

    # 5. Thumbnail at the payoff.
    report(0.97, "thumbnail")
    pick = pick_thumbnail(
        out_path,
        duration,
        max(0.0, min(duration - 0.1, to_clip_time(parts, durations, cand.peak_time))),
        cfg.face_model_path,
        thumb_path,
        alternatives=cfg.clip.thumbnail_alternatives,
    )
    shutil.rmtree(tmp, ignore_errors=True)
    report(1.0, "done")
    return RenderedClip(
        path=out_path,
        thumbnail=pick.path,
        srt=srt_path,
        ass=ass_path,
        thumbnail_time=pick.time,
        thumbnail_alternatives=tuple(pick.alternatives),
    )
