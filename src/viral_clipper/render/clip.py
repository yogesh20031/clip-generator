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
from viral_clipper.render.ffmpeg import loudnorm_filter, measure_loudness, run_ffmpeg, write_thumbnail
from viral_clipper.render.hook_overlay import render_hook

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderedClip:
    path: Path
    thumbnail: Path
    srt: Path
    ass: Path


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
    duration = cand.end - cand.start
    src = Path(analysis.video.path)

    def report(frac: float, msg: str) -> None:
        if progress:
            progress(frac, f"{name}: {msg}")

    # 1. Captions + hook overlays (Pillow).
    report(0.02, "rendering captions")
    words = analysis.transcript.words_between(cand.start, cand.end)
    inputs: list[str] = ["-ss", f"{cand.start:.3f}", "-to", f"{cand.end:.3f}", "-i", str(src)]
    overlay_filters: list[str] = []
    input_index = 1
    if cfg.captions.enabled and words:
        items, lines = cap.build_caption_sequence(
            words, cand.start, duration, size, cfg.captions, cfg.font_path, tmp / "captions"
        )
        concat = cap.write_concat_list(items, tmp / "captions.txt")
        cap.write_subtitle_files(lines, cand.start, srt_path, ass_path)
        inputs += ["-f", "concat", "-safe", "0", "-i", str(concat)]
        overlay_filters.append(f"[{input_index}:v]")
        input_index += 1
    else:
        srt_path.write_text("", encoding="utf-8")
        ass_path.write_text("", encoding="utf-8")
    if cfg.captions.hook_enabled and hook_text.strip():
        hook_png = render_hook(hook_text, size, cfg.captions, cfg.font_path, tmp / "hook.png")
        inputs += [
            "-loop",
            "1",
            "-framerate",
            str(cfg.clip.fps),
            "-t",
            f"{cfg.captions.hook_duration_s:.2f}",
            "-i",
            str(hook_png),
        ]
        overlay_filters.append(f"[{input_index}:v]")
        input_index += 1

    # 2. Reframe plan (face -> motion -> centre).
    report(0.10, "planning the crop")
    plan = plan_crop(analysis, cand.start, cand.end, cfg.clip.width, cfg.clip.height, cfg.face_model_path)
    if plan.axis == "x":
        crop = f"crop={plan.crop_w}:{plan.crop_h}:x='{plan.expression()}':y=0"
    else:
        crop = f"crop={plan.crop_w}:{plan.crop_h}:x=0:y='{plan.expression()}'"

    # 3. Loudness pass 1.
    report(0.15, "measuring loudness")
    measured = measure_loudness(src, cand.start, cand.end, cfg.clip)

    # 4. Pass 2: the real render.
    chain = [
        f"[0:v]{crop},scale={cfg.clip.width}:{cfg.clip.height}:flags=lanczos,fps={cfg.clip.fps},format=yuv420p[v0]"
    ]
    last = "[v0]"
    for i, label in enumerate(overlay_filters):
        out = f"[v{i + 1}]"
        chain.append(f"{last}{label}overlay=0:0:eof_action=pass:format=auto{out}")
        last = out
    chain.append(f"{last}format=yuv420p[vout]")
    chain.append(f"[0:a]{loudnorm_filter(measured, cfg.clip)},aresample=48000[aout]")
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
        "-shortest",
        str(out_path),
    ]
    run_ffmpeg(args, duration, lambda f, _m: report(0.2 + 0.75 * f, "encoding"), what=name)

    # 5. Thumbnail at the payoff.
    report(0.97, "thumbnail")
    write_thumbnail(out_path, max(0.0, min(duration - 0.1, cand.peak_time - cand.start)), thumb_path)
    shutil.rmtree(tmp, ignore_errors=True)
    report(1.0, "done")
    return RenderedClip(path=out_path, thumbnail=thumb_path, srt=srt_path, ass=ass_path)
