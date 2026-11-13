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

# Lines whisper invents over music, engine noise or silence (it learned them from YouTube subtitles).
_STOCK_PHRASES = re.compile(
    r"(we'll be right back|thanks? (?:you )?for watching|please subscribe|subscribe to|"
    r"see you (?:in the )?next (?:time|video)|subtitles? by|amara\.org|transcribed by)",
    re.IGNORECASE,
)
# Scripts that never appear in a real English line ("Contentña tends to remain дав высolia").
_FOREIGN_SCRIPT = re.compile(
    "["
    "\u0400-\u04ff"  # Cyrillic
    "\u0590-\u06ff"  # Hebrew, Arabic
    "\u0900-\u0dff"  # Indic
    "\u0e00-\u0e7f"  # Thai
    "\u1100-\u11ff\u3130-\u318f\uac00-\ud7af"  # Hangul
    "\u3040-\u30ff\u4e00-\u9fff"  # Kana, CJK
    "]"
)
# Sentences at least this long and confident count as real speech ("anchors").
_ANCHOR_WORDS = 4
_SHOUT_NEAR_SPEECH_S = 30.0
# Vietnamese-only letters: whisper slips into Vietnamese when it hallucinates over gameplay audio.
_VIETNAMESE = re.compile(r"[ăđơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.IGNORECASE)


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


def drop_hallucinations(transcript: Transcript, min_prob: float) -> Transcript:
    """Remove sentences whisper made up. Videos with no commentary (gameplay, music) still get a
    "transcript" of confident-looking nonsense; captioning or story-building on it ruins the clip.

    Real shouts ("Oh!", "Go Jonah!") score as low as hallucinations, so confidence alone can't
    tell them apart. A short low-confidence line is kept only when real speech is nearby, which is
    true for a shout in a commentated video and false for noise over raw gameplay.

    Runs on load as well as after transcription, so a cached transcript is filtered with the
    current threshold without re-running whisper.
    """
    if transcript.is_empty:
        return transcript
    english = (transcript.language or "en").startswith("en")
    plausible: list[tuple[Sentence, float]] = []
    for sentence in transcript.sentences:
        if not sentence.words:
            continue
        prob = sum(w.prob for w in sentence.words) / len(sentence.words)
        if _STOCK_PHRASES.search(sentence.text) and prob < 0.8:
            continue
        if english and (_FOREIGN_SCRIPT.search(sentence.text) or _VIETNAMESE.search(sentence.text)):
            continue
        plausible.append((sentence, prob))

    def is_anchor(sentence: Sentence, prob: float) -> bool:
        return prob >= min_prob and len(sentence.words) >= _ANCHOR_WORDS

    anchors = [s.start for s, prob in plausible if is_anchor(s, prob)]
    kept: list[Sentence] = []
    for sentence, prob in plausible:
        near_speech = any(abs(t - sentence.start) <= _SHOUT_NEAR_SPEECH_S for t in anchors)
        # A long line whisper had almost no confidence in is invented even in a talky video.
        rambling = len(sentence.words) >= 8 and prob < min_prob / 2
        if is_anchor(sentence, prob) or (near_speech and not rambling):
            kept.append(sentence)
    dropped = len(transcript.sentences) - len(kept)
    if dropped:
        log.info("transcript: dropped %d of %d sentences as whisper hallucinations", dropped, len(transcript.sentences))
    return transcript.model_copy(update={"sentences": kept, "words": [w for s in kept for w in s.words]})


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
