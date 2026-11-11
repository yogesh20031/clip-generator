"""Shared fixtures. The sample video is synthesized with FFmpeg so no copyrighted media ships.

Layout of sample.mp4 (40 s, 640x360, 30 fps, stereo audio):
  0-10 s  : slow test pattern, quiet 220 Hz tone        (boring)
  10-11 s : LOUD 880 Hz burst + hard scene change         (first "event")
  11-25 s : fast-moving pattern, medium tone              (action)
  25-26 s : LOUD 1760 Hz burst + scene change             (second "event")
  26-40 s : slow pattern, quiet                           (boring)
If macOS `say` exists, synthetic speech is mixed in so the real-ASR smoke test has words to find.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from viral_clipper.config import Config, load_config
from viral_clipper.models import Sentence, Transcript, Word

SAMPLE_DURATION = 40.0


def _ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        pytest.skip("ffmpeg is required for the test-suite")
    return found


def _speech_track(tmp: Path) -> Path | None:
    """macOS-only synthetic narration with known words at known times."""
    say = shutil.which("say")
    if say is None:
        return None
    text = (
        "Welcome back everyone. Today we are giving away one hundred thousand dollars. "
        "Wait for it. Oh my god, no way, he actually did it. "
        "But then everything changed. This is insane. Nobody expected this twist at all."
    )
    aiff = tmp / "speech.aiff"
    try:
        subprocess.run([say, "-v", "Samantha", "-r", "175", "-o", str(aiff), text], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return aiff


def build_sample_video(dest: Path) -> Path:
    ffmpeg = _ffmpeg()
    tmp = dest.parent
    speech = _speech_track(tmp)

    # Video: three segments with different patterns, concatenated = two hard cuts.
    video_filter = (
        "testsrc2=size=640x360:rate=30:duration=10[v0];"
        "life=size=640x360:rate=30:ratio=0.35:mold=10:life_color=#ffffff,trim=duration=15,setpts=PTS-STARTPTS[v1];"
        "smptebars=size=640x360:rate=30:duration=15[v2];"
        "[v0][v1][v2]concat=n=3:v=1:a=0[vout]"
    )
    # Audio: quiet tone with two loud bursts at 10 s and 25 s.
    audio_filter = (
        "sine=frequency=220:duration=40,volume=0.05[base];"
        "sine=frequency=880:duration=1,volume=0.9,adelay=10000|10000[b1];"
        "sine=frequency=1760:duration=1,volume=0.9,adelay=25000|25000[b2];"
        "[base][b1][b2]amix=inputs=3:duration=first:normalize=0[aout]"
    )
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    inputs: list[str] = []
    if speech is not None:
        inputs = ["-i", str(speech)]
        audio_filter = audio_filter.replace(
            "[aout]",
            "[tones];[0:a]adelay=12000|12000,volume=0.12[sp];[tones][sp]amix=inputs=2:duration=first:normalize=0[aout]",
        )
    cmd += inputs
    cmd += [
        "-filter_complex",
        video_filter + ";" + audio_filter,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-t",
        str(SAMPLE_DURATION),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return dest


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("sample")
    return build_sample_video(tmp / "sample.mp4")


@pytest.fixture(scope="session")
def test_config(tmp_path_factory: pytest.TempPathFactory) -> Config:
    cfg = load_config()
    out = tmp_path_factory.mktemp("output")
    cfg = cfg.model_copy(deep=True)
    cfg.paths.output_dir = str(out)
    cfg.paths.log_dir = str(out / "logs")
    cfg.whisper.backend = "none"  # real ASR only in tests marked slow
    cfg.llm.provider = "none"
    return cfg


def fake_transcript(duration: float = SAMPLE_DURATION) -> Transcript:
    """A deterministic transcript covering the sample video with a sentence every ~3 s."""
    phrases = [
        "welcome back everyone.",
        "today we are giving away one hundred thousand dollars.",
        "wait for it.",
        "oh my god no way he actually did it.",
        "but then everything changed.",
        "this is insane.",
        "nobody expected this twist at all.",
        "the cops showed up and the car exploded.",
        "that was the craziest thing I have ever seen.",
        "let me know what you think in the comments.",
        "and subscribe for more.",
        "see you next time.",
    ]
    words: list[Word] = []
    sentences: list[Sentence] = []
    t = 1.0
    for phrase in phrases:
        toks = phrase.split()
        sent_words: list[Word] = []
        for tok in toks:
            w = Word(text=tok, start=round(t, 2), end=round(t + 0.28, 2), prob=0.95)
            sent_words.append(w)
            t += 0.32
        sentences.append(Sentence(text=phrase, start=sent_words[0].start, end=sent_words[-1].end, words=sent_words))
        words.extend(sent_words)
        t += 0.7
        if t > duration - 1:
            break
    return Transcript(language="en", backend="fixture", model="fixture", words=words, sentences=sentences)


@pytest.fixture
def transcript() -> Transcript:
    return fake_transcript()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
