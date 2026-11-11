"""clips.json / clips.csv writers and readers."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from viral_clipper.errors import InvalidSourceError
from viral_clipper.models import ClipMetadata, ClipRecord, ClipVideoResult, OutputEntry, Platform

log = logging.getLogger(__name__)

CSV_COLUMNS = [
    "clip",
    "file",
    "start",
    "end",
    "duration",
    "score",
    "platform",
    "title",
    "hashtags",
    "description",
    "hook",
    "reasons",
]


PLATFORM_LABELS = {
    Platform.YOUTUBE_SHORTS: "YouTube Shorts",
    Platform.TIKTOK: "TikTok",
    Platform.INSTAGRAM_REELS: "Instagram Reels",
    Platform.FACEBOOK_REELS: "Facebook Reels",
}


def _fmt_t(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def clip_text(clip: ClipRecord, video_title: str) -> str:
    """Human-readable copy sheet for one clip: paste straight into the upload form."""
    header = (
        f'{Path(clip.path).name}  |  from "{video_title}"  |  '
        f"{_fmt_t(clip.start)}-{_fmt_t(clip.end)} ({clip.duration:.0f}s)  |  score {clip.score:.0f}/100"
    )
    lines = [
        header,
        f"Why: {'; '.join(clip.reasons)}",
        "",
        f"HOOK (on-screen, first 2s): {clip.hook}",
        "",
    ]
    for platform, meta in clip.metadata.items():
        lines += [
            f"==== {PLATFORM_LABELS.get(platform, platform.value)} ====",
            f"Title: {meta.title}",
            f"Hashtags: {' '.join(meta.hashtags)}",
            "Description:",
            meta.description,
            "",
        ]
    if clip.transcript_text:
        lines += ["==== Transcript ====", clip.transcript_text, ""]
    return "\n".join(lines)


def write_clip_text(clip: ClipRecord, video_title: str) -> Path:
    dest = Path(clip.path).with_suffix(".txt")
    dest.write_text(clip_text(clip, video_title), encoding="utf-8")
    return dest


def write_outputs(result: ClipVideoResult) -> None:
    Path(result.clips_json).write_text(result.model_dump_json(indent=2), encoding="utf-8")
    for clip in result.clips:
        clip.metadata_txt = str(write_clip_text(clip, result.video_title))
    with Path(result.clips_csv).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for clip in result.clips:
            for platform, meta in clip.metadata.items():
                writer.writerow(
                    {
                        "clip": clip.index,
                        "file": Path(clip.path).name,
                        "start": f"{clip.start:.2f}",
                        "end": f"{clip.end:.2f}",
                        "duration": f"{clip.duration:.2f}",
                        "score": f"{clip.score:.1f}",
                        "platform": platform.value,
                        "title": meta.title,
                        "hashtags": " ".join(meta.hashtags),
                        "description": meta.description.replace("\n", " / "),
                        "hook": meta.hook,
                        "reasons": "; ".join(clip.reasons),
                    }
                )


def read_result(clips_json: Path) -> ClipVideoResult:
    return ClipVideoResult.model_validate_json(clips_json.read_text(encoding="utf-8"))


def list_outputs(output_root: Path) -> list[OutputEntry]:
    entries: list[OutputEntry] = []
    if not output_root.exists():
        return entries
    for clips_json in sorted(output_root.glob("*/clips.json")):
        try:
            result = read_result(clips_json)
        except (OSError, ValueError) as exc:
            log.warning("skipping unreadable %s: %s", clips_json, exc)
            continue
        entries.append(
            OutputEntry(
                video_title=result.video_title,
                output_dir=result.output_dir,
                clips_json=str(clips_json),
                clip_count=len(result.clips),
                clips=result.clips,
            )
        )
    return entries


def find_clip(clip_path: Path, output_root: Path) -> tuple[ClipVideoResult, ClipRecord, Path]:
    """Locate the clips.json that owns `clip_path`."""
    clip_path = clip_path.expanduser().resolve()
    candidates = [clip_path.parent / "clips.json", *output_root.glob("*/clips.json")]
    for clips_json in candidates:
        if not clips_json.exists():
            continue
        result = read_result(clips_json)
        for clip in result.clips:
            if Path(clip.path).resolve() == clip_path:
                return result, clip, clips_json
    raise InvalidSourceError(f"{clip_path} is not a clip produced by viral-clipper (no clips.json lists it).")


def update_clip_metadata(clip_path: Path, platform: Platform, metadata: ClipMetadata, output_root: Path) -> ClipRecord:
    result, clip, _clips_json = find_clip(clip_path, output_root)
    clip.metadata[platform] = metadata.model_copy(update={"platform": platform})
    if metadata.hook.strip():
        clip.hook = metadata.hook.strip()
    write_outputs(result)
    return clip
