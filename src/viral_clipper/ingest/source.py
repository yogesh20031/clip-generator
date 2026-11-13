"""Turn `source` (URL or local path) into a VideoInfo plus the per-video work folder."""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

from viral_clipper.config import Config
from viral_clipper.errors import InvalidSourceError, UnsupportedFormatError
from viral_clipper.ingest import youtube
from viral_clipper.ingest.ffprobe import SUPPORTED_EXTENSIONS, probe
from viral_clipper.models import VideoInfo

log = logging.getLogger(__name__)


def slugify(title: str, max_len: int = 60) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_title).strip("-").lower()
    slug = slug[:max_len].rstrip("-")
    return slug or "video"


def work_dir_for(cfg: Config, slug: str) -> Path:
    return cfg.output_root / slug


def resolve_source(
    source: str,
    cfg: Config,
    progress: youtube.ProgressCallback | None = None,
) -> tuple[VideoInfo, Path]:
    """Returns (video, work_dir). Downloads remote sources into work_dir/source.mp4."""
    source = source.strip()
    if not source:
        raise InvalidSourceError("Empty source.")

    if youtube.is_url(source):
        info = youtube.fetch_info(source)
        slug = slugify(info.title)
        work_dir = work_dir_for(cfg, slug)
        path = youtube.download(info.url, work_dir / "source.mp4", progress)
        meta = probe(path)
        video = VideoInfo(
            path=str(path),
            title=info.title,
            slug=slug,
            duration=meta.duration,
            width=meta.width,
            height=meta.height,
            fps=meta.fps,
            source_url=info.url,
            video_id=info.video_id,
            channel=info.channel,
            license=info.license,
        )
        return video, work_dir

    path = Path(source).expanduser()
    if not path.exists():
        raise InvalidSourceError(f"{source} does not exist and is not a URL.")
    if not path.is_file():
        raise InvalidSourceError(f"{source} is not a file.")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(f"{path.name} is not a supported video container.")
    meta = probe(path)
    slug = slugify(path.stem)
    video = VideoInfo(
        path=str(path.resolve()),
        title=path.stem,
        slug=slug,
        duration=meta.duration,
        width=meta.width,
        height=meta.height,
        fps=meta.fps,
    )
    return video, work_dir_for(cfg, slug)
