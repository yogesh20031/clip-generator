"""mlx-whisper backend (Apple Silicon GPU)."""

from __future__ import annotations

import logging
from pathlib import Path

from viral_clipper.models import Transcript, Word

log = logging.getLogger(__name__)

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"


def resolve_model(name: str) -> str:
    if name == "auto":
        return DEFAULT_MODEL
    # Allow short names like "small" to map onto the mlx-community conversions.
    if "/" not in name:
        return f"mlx-community/whisper-{name}"
    return name


def transcribe(wav_path: Path, model: str, language: str | None) -> Transcript:
    import mlx_whisper

    repo = resolve_model(model)
    log.info("transcribing with mlx-whisper %s", repo)
    result = mlx_whisper.transcribe(
        str(wav_path),
        path_or_hf_repo=repo,
        word_timestamps=True,
        language=language,
        condition_on_previous_text=False,
        verbose=None,
    )
    words: list[Word] = []
    for segment in result.get("segments", []):
        for w in segment.get("words", []):
            text = str(w.get("word", "")).strip()
            if not text:
                continue
            words.append(
                Word(
                    text=text,
                    start=float(w["start"]),
                    end=float(w["end"]),
                    prob=float(w.get("probability", 1.0)),
                )
            )
    return Transcript(language=str(result.get("language", language or "en")), backend="mlx", model=repo, words=words)
