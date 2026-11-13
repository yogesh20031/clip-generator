"""YouTube (and anything yt-dlp supports) download with error mapping."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from viral_clipper.errors import (
    DownloadError,
    InvalidSourceError,
    PrivateVideoError,
    UnavailableVideoError,
)

log = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]

_URL_RE = re.compile(r"^(https?://|www\.)", re.IGNORECASE)
# Best mp4 up to 1080p; fall back to anything we can merge into mp4.
_FORMAT = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best"


def is_url(source: str) -> bool:
    return bool(_URL_RE.match(source.strip()))


@dataclass(frozen=True)
class RemoteInfo:
    video_id: str
    title: str
    url: str
    duration: float | None
    channel: str = ""
    license: str = ""


def _map_error(exc: Exception, url: str) -> DownloadError:
    text = str(exc)
    lowered = text.lower()
    if "private video" in lowered or "members-only" in lowered or "sign in to confirm" in lowered:
        return PrivateVideoError(f"{url} is private or requires sign-in.")
    if (
        "video unavailable" in lowered
        or "has been removed" in lowered
        or "not available in your country" in lowered
        or "no video formats found" in lowered
        or "this video is not available" in lowered
    ):
        return UnavailableVideoError(f"{url} is unavailable.")
    if "unsupported url" in lowered or "is not a valid url" in lowered or "incomplete youtube id" in lowered:
        return InvalidSourceError(f"{url} is not a URL yt-dlp can download.")
    # Strip yt-dlp's ANSI prefix noise to keep the message readable.
    clean = re.sub(r"\x1b\[[0-9;]*m", "", text).replace("ERROR: ", "").strip()
    return DownloadError(f"Download failed for {url}: {clean[:300]}")


def _ydl_opts(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "format": _FORMAT,
        "merge_output_format": "mp4",
        "retries": 3,
        "logger": _YdlLogger(),
    }
    if extra:
        opts.update(extra)
    return opts


class _YdlLogger:
    def debug(self, msg: str) -> None:  # yt-dlp routes info through debug
        if not msg.startswith("[debug]"):
            log.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
        log.warning("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        log.error("yt-dlp: %s", msg)


def fetch_info(url: str) -> RemoteInfo:
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(_ydl_opts({"skip_download": True})) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise _map_error(exc, url) from exc
    except Exception as exc:  # yt-dlp raises a wide variety of things for bad input
        raise _map_error(exc, url) from exc
    if info is None:
        raise UnavailableVideoError(f"No metadata returned for {url}.")
    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        if not entries:
            raise InvalidSourceError(f"{url} is an empty playlist.")
        info = entries[0]
    return RemoteInfo(
        video_id=str(info.get("id", "")),
        title=str(info.get("title") or info.get("id") or "video"),
        url=str(info.get("webpage_url") or url),
        duration=float(info["duration"]) if info.get("duration") else None,
        channel=str(info.get("channel") or info.get("uploader") or ""),
        license=str(info.get("license") or ""),
    )


def download(url: str, dest: Path, progress: ProgressCallback | None = None) -> Path:
    """Download `url` to `dest` (an .mp4 path). Returns dest. Skips if dest already exists."""
    import yt_dlp

    if dest.exists() and dest.stat().st_size > 0:
        log.info("Using cached download %s", dest)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)

    def hook(status: dict[str, Any]) -> None:
        if progress is None:
            return
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            frac = (done / total) if total else 0.0
            progress(frac, f"Downloading {frac * 100:.0f}%")
        elif status.get("status") == "finished":
            progress(1.0, "Download finished, merging streams")

    opts = _ydl_opts(
        {
            "outtmpl": str(dest.with_suffix("")) + ".%(ext)s",
            "progress_hooks": [hook],
        }
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise _map_error(exc, url) from exc
    if not dest.exists():
        # yt-dlp may have produced a different container if mp4 merge was impossible.
        candidates = sorted(dest.parent.glob(dest.stem + ".*"))
        media = [c for c in candidates if c.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
        if not media:
            raise DownloadError(f"yt-dlp finished but no media file was written to {dest.parent}.")
        return media[0]
    return dest
