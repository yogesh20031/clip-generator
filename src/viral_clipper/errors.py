"""Error hierarchy. Every error carries a message that is safe to show to the model/user."""

from __future__ import annotations


class ClipperError(Exception):
    """Base class. `hint` tells the user what to do about it."""

    hint: str = ""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        if hint is not None:
            self.hint = hint

    def user_message(self) -> str:
        text = str(self)
        return f"{text} {self.hint}".strip() if self.hint else text


class FFmpegMissingError(ClipperError):
    hint = (
        "Install FFmpeg and make sure `ffmpeg` and `ffprobe` are on PATH "
        "(macOS: `brew install ffmpeg`, Windows: winget install Gyan.FFmpeg)."
    )


class InvalidSourceError(ClipperError):
    hint = "Pass a YouTube URL (https://www.youtube.com/watch?v=...) or a path to an mp4/mov/mkv file."


class UnsupportedFormatError(ClipperError):
    hint = "Supported containers: .mp4, .mov, .mkv, .webm, .m4v."


class DownloadError(ClipperError):
    hint = "Check that the video is public, not age-gated, and that the URL is correct."


class PrivateVideoError(DownloadError):
    hint = "The video is private or members-only; viral-clipper can only download public videos."


class UnavailableVideoError(DownloadError):
    hint = "The video was removed, is geo-blocked, or the URL is wrong."


class AnalysisError(ClipperError):
    hint = "Re-run with force=true to rebuild the analysis cache."


class RenderError(ClipperError):
    hint = "Check logs/viral-clipper.log for the FFmpeg command and its stderr."


class ProfileNotFoundError(ClipperError):
    hint = "Available niches are the yaml files in the profiles/ folder (gta6, mrbeast, generic)."


class NoClipsError(ClipperError):
    hint = "Try a longer video, a smaller min_len, or a different niche profile."


class LLMUnavailableError(ClipperError):
    hint = (
        "Set ANTHROPIC_API_KEY (or run `ant auth login`) and set llm.provider to 'anthropic' "
        "in config.yaml, or leave llm.provider at 'auto' to use the template engine."
    )
