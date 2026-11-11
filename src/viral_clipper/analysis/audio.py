"""Audio signals: loudness, onsets, laughter/shout-band spikes, silence.

Everything is computed with librosa on a 16 kHz mono wav and resampled onto the shared grid
(default 4 Hz). Curves hold raw values; the scorer normalizes per video.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import numpy as np

from viral_clipper.errors import AnalysisError
from viral_clipper.ingest.ffprobe import ffmpeg_path
from viral_clipper.models import Event, SignalCurve

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
HOP = 512  # 32 ms at 16 kHz


def extract_wav(video_path: str | Path, wav_path: Path) -> Path:
    """Mono 16 kHz PCM wav shared by whisper and librosa."""
    if wav_path.exists() and wav_path.stat().st_size > 1000:
        return wav_path
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        str(wav_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise AnalysisError(f"Audio extraction failed: {result.stderr.strip()[:300]}")
    return wav_path


def _to_grid(values: np.ndarray, src_rate: float, rate_hz: float, duration: float, reduce: str) -> np.ndarray:
    """Bin a frame-rate series onto the output grid with mean or max per bin."""
    n_out = max(1, int(np.ceil(duration * rate_hz)))
    out = np.zeros(n_out, dtype=np.float32)
    if values.size == 0:
        return out
    times = np.arange(values.size) / src_rate
    bins = np.minimum((times * rate_hz).astype(int), n_out - 1)
    if reduce == "max":
        np.maximum.at(out, bins, values.astype(np.float32))
    else:
        counts = np.bincount(bins, minlength=n_out).astype(np.float32)
        sums = np.bincount(bins, weights=values, minlength=n_out).astype(np.float32)
        out = np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0)
    return out


def rolling_z(values: np.ndarray, window: int) -> np.ndarray:
    """Z-score of each sample against the *preceding* `window` samples.

    Causal on purpose: a spike is a surprise relative to what came just before it, which is
    how viewers hear it. A centred window would let a loud passage right after the spike
    swallow it.
    """
    values = np.asarray(values, dtype=np.float64)
    n = values.size
    if n < 2:
        return np.zeros(n, dtype=np.float32)
    window = max(2, min(window, n))
    # Prepend the first value so early samples compare against something sensible.
    padded = np.concatenate([np.full(window, values[0]), values])
    csum = np.cumsum(np.insert(padded, 0, 0.0))
    csq = np.cumsum(np.insert(padded * padded, 0, 0.0))
    idx = np.arange(n) + window  # position of each sample in `padded`
    mean = (csum[idx] - csum[idx - window]) / window  # trailing window, excludes current sample
    sq = (csq[idx] - csq[idx - window]) / window
    std = np.sqrt(np.maximum(sq - mean * mean, 1e-8))
    global_std = float(values.std()) or 1.0
    std = np.maximum(std, 0.25 * global_std)  # avoid blowing up in flat passages
    return ((values - mean) / std).astype(np.float32)


def local_maxima(values: np.ndarray, threshold: float, min_distance: int) -> list[int]:
    """Indices of peaks above threshold, at least min_distance apart (greedy by height)."""
    idx = np.where(values > threshold)[0]
    if idx.size == 0:
        return []
    order = idx[np.argsort(values[idx])[::-1]]
    chosen: list[int] = []
    for i in order:
        if all(abs(i - j) >= min_distance for j in chosen):
            chosen.append(int(i))
    return sorted(chosen)


def analyze_audio(
    wav_path: Path,
    duration: float,
    rate_hz: float,
    silence_db: float,
    spike_z: float,
) -> tuple[dict[str, SignalCurve], list[Event]]:
    import librosa

    y, sr = librosa.load(str(wav_path), sr=SAMPLE_RATE, mono=True)
    if y.size == 0:
        raise AnalysisError("The audio track is empty.")
    frame_rate = sr / HOP

    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0]
    rms_db = librosa.amplitude_to_db(rms + 1e-6, ref=1.0)
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)

    # Laughter / shouting energy lives mostly in 300-3000 Hz; compare it to its own history.
    stft = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    band = (freqs >= 300) & (freqs <= 3000)
    band_energy = stft[band].sum(axis=0)
    band_db = librosa.amplitude_to_db(band_energy + 1e-6, ref=1.0)

    rms_grid = _to_grid(rms_db, frame_rate, rate_hz, duration, "mean")
    onset_grid = _to_grid(onset, frame_rate, rate_hz, duration, "max")
    band_grid = _to_grid(band_db, frame_rate, rate_hz, duration, "mean")
    silence_grid = _to_grid((rms_db < silence_db).astype(np.float32), frame_rate, rate_hz, duration, "mean")

    window = int(10 * rate_hz)  # 10 s of context
    rms_z = rolling_z(rms_grid, window)
    band_z = rolling_z(band_grid, window)

    # Loudness spikes: sudden jumps relative to the last 10 s, not absolute loudness.
    events = [
        Event(time=i / rate_hz, strength=float(rms_z[i]), kind="audio_spike")
        for i in local_maxima(rms_z, spike_z, int(rate_hz))  # >= 1 s apart
    ]
    # Shout/laugh bursts: band energy jumps while overall loudness also rises.
    laugh_idx = local_maxima(np.minimum(band_z, rms_z + 1.0), spike_z - 0.5, int(rate_hz))
    events += [Event(time=i / rate_hz, strength=float(band_z[i]), kind="laugh_shout") for i in laugh_idx]
    events.sort(key=lambda e: e.time)

    curves = {
        "audio_rms_db": SignalCurve(name="audio_rms_db", rate_hz=rate_hz, values=rms_grid.tolist()),
        "audio_rms_z": SignalCurve(name="audio_rms_z", rate_hz=rate_hz, values=rms_z.tolist()),
        "audio_onset": SignalCurve(name="audio_onset", rate_hz=rate_hz, values=onset_grid.tolist()),
        "audio_band_z": SignalCurve(name="audio_band_z", rate_hz=rate_hz, values=band_z.tolist()),
        "silence": SignalCurve(name="silence", rate_hz=rate_hz, values=silence_grid.tolist()),
    }
    log.info(
        "audio: %d grid samples, %d spikes, %d laugh/shout bursts",
        rms_grid.size,
        len(events) - len(laugh_idx),
        len(laugh_idx),
    )
    return curves, events
