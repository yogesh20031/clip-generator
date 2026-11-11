"""faster-whisper backend (CUDA or CPU)."""

from __future__ import annotations

import logging
from pathlib import Path

from viral_clipper.models import Transcript, Word

log = logging.getLogger(__name__)


def cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # ctranslate2 missing or broken CUDA runtime
        return False


def resolve_model(name: str, device: str) -> str:
    if name != "auto":
        return name
    return "large-v3-turbo" if device == "cuda" else "small"


def resolve_device(device: str) -> str:
    if device == "auto":
        return "cuda" if cuda_available() else "cpu"
    return device


def resolve_compute_type(compute_type: str, device: str) -> str:
    if compute_type != "auto":
        return compute_type
    return "int8_float16" if device == "cuda" else "int8"


def transcribe(
    wav_path: Path,
    model: str,
    device: str,
    compute_type: str,
    language: str | None,
    vad_filter: bool,
    beam_size: int,
) -> Transcript:
    from faster_whisper import WhisperModel

    device = resolve_device(device)
    model_name = resolve_model(model, device)
    compute = resolve_compute_type(compute_type, device)
    log.info("transcribing with faster-whisper %s on %s (%s)", model_name, device, compute)
    whisper = WhisperModel(model_name, device=device, compute_type=compute)
    segments, info = whisper.transcribe(
        str(wav_path),
        word_timestamps=True,
        vad_filter=vad_filter,
        beam_size=beam_size,
        language=language,
        condition_on_previous_text=False,
    )
    words: list[Word] = []
    for segment in segments:  # generator: transcription happens here
        for w in segment.words or []:
            text = w.word.strip()
            if text:
                words.append(Word(text=text, start=float(w.start), end=float(w.end), prob=float(w.probability)))
    return Transcript(language=info.language, backend="faster_whisper", model=model_name, words=words)
