"""Backend selection and sentence building for transcripts."""

from __future__ import annotations

import importlib.util
import logging
import platform
import re
from pathlib import Path

from viral_clipper.config import WhisperConfig
from viral_clipper.models import Sentence, Transcript, Word

log = logging.getLogger(__name__)

_TERMINAL = re.compile(r"[.!?…]+[\"')\]]*$")
MAX_SENTENCE_WORDS = 28


def pick_backend(cfg: WhisperConfig) -> str:
    if cfg.backend != "auto":
        return cfg.backend
    on_apple_silicon = platform.system() == "Darwin" and platform.machine() == "arm64"
    if on_apple_silicon and importlib.util.find_spec("mlx_whisper") is not None:
        return "mlx"
    return "faster_whisper"


def transcribe(wav_path: Path, cfg: WhisperConfig, pause_s: float) -> Transcript:
    backend = pick_backend(cfg)
    if backend == "none":
        return Transcript(backend="none")
    if backend == "mlx":
        from viral_clipper.analysis import asr_mlx

        transcript = asr_mlx.transcribe(wav_path, cfg.model, cfg.language)
    else:
        from viral_clipper.analysis import asr_faster

        transcript = asr_faster.transcribe(
            wav_path,
            model=cfg.model,
            device=cfg.device,
            compute_type=cfg.compute_type,
            language=cfg.language,
            vad_filter=cfg.vad_filter,
            beam_size=cfg.beam_size,
        )
    transcript.words = _clean_words(transcript.words)
    transcript.sentences = build_sentences(transcript.words, pause_s)
    log.info(
        "transcript: %d words, %d sentences (%s)", len(transcript.words), len(transcript.sentences), transcript.backend
    )
    return transcript


def _clean_words(words: list[Word]) -> list[Word]:
    """Drop zero-length and out-of-order words that whisper occasionally emits."""
    cleaned: list[Word] = []
    last_end = 0.0
    for w in words:
        start = max(w.start, last_end - 0.05)
        end = max(w.end, start + 0.02)
        cleaned.append(Word(text=w.text, start=start, end=end, prob=w.prob))
        last_end = end
    return cleaned


def build_sentences(words: list[Word], pause_s: float) -> list[Sentence]:
    """Split on terminal punctuation, long pauses, or a hard word cap."""
    sentences: list[Sentence] = []
    current: list[Word] = []

    def flush() -> None:
        if current:
            sentences.append(
                Sentence(
                    text=" ".join(w.text for w in current),
                    start=current[0].start,
                    end=current[-1].end,
                    words=list(current),
                )
            )
            current.clear()

    for i, w in enumerate(words):
        if current and (w.start - current[-1].end) > pause_s:
            flush()
        current.append(w)
        next_gap = (words[i + 1].start - w.end) if i + 1 < len(words) else 0.0
        if _TERMINAL.search(w.text) or len(current) >= MAX_SENTENCE_WORDS or next_gap > pause_s:
            flush()
    flush()
    return sentences
