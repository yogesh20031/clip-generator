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


def write_outputs(result: ClipVideoResult) -> None:
    Path(result.clips_json).write_text(result.model_dump_json(indent=2), encoding="utf-8")
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
