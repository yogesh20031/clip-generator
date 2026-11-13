"""Run every analyzer once per video and cache the result as analysis.json."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from viral_clipper.analysis import audio as audio_mod
from viral_clipper.analysis import motion as motion_mod
from viral_clipper.analysis import scenes as scenes_mod
from viral_clipper.analysis import transcribe as transcribe_mod
from viral_clipper.analysis.events import fuse_events
from viral_clipper.config import Config
from viral_clipper.errors import AnalysisError
from viral_clipper.ingest.ffprobe import probe
from viral_clipper.models import AnalysisResult, SignalCurve, Transcript, VideoInfo
from viral_clipper.progress import ProgressFn, StageProgress

log = logging.getLogger(__name__)

STAGES = {"audio": 1.0, "transcribe": 6.0, "scenes": 2.0, "motion": 2.0, "events": 0.2}


def fingerprint(video: VideoInfo, cfg: Config) -> str:
    p = Path(video.path)
    stat = p.stat()
    h = hashlib.sha1()
    # Name + size + mtime, not the full path: moving the output folder must not throw the cache away.
    h.update(f"{p.name}|{stat.st_size}|{int(stat.st_mtime)}".encode())
    h.update(json.dumps(cfg.analysis.model_dump(), sort_keys=True).encode())
    h.update(json.dumps(cfg.whisper.model_dump(), sort_keys=True).encode())
    return h.hexdigest()[:16]


def cache_path(work_dir: Path) -> Path:
    return work_dir / "analysis.json"


def load_cached(work_dir: Path, fp: str) -> AnalysisResult | None:
    path = cache_path(work_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("fingerprint") != fp:
            return None
        return AnalysisResult.model_validate(data)
    except (OSError, ValueError) as exc:
        log.warning("ignoring unreadable analysis cache %s: %s", path, exc)
        return None


def _transcript_path(work_dir: Path) -> Path:
    return work_dir / "transcript.json"


def _save_transcript(work_dir: Path, fp: str, transcript: Transcript) -> None:
    payload = {"fingerprint": fp, "transcript": transcript.model_dump()}
    _transcript_path(work_dir).write_text(json.dumps(payload), encoding="utf-8")


def _load_transcript(work_dir: Path, fp: str) -> Transcript | None:
    path = _transcript_path(work_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("fingerprint") != fp:
            return None
        return Transcript.model_validate(data["transcript"])
    except (OSError, ValueError, KeyError) as exc:
        log.warning("ignoring unreadable transcript cache %s: %s", path, exc)
        return None


def analyze(
    video: VideoInfo,
    work_dir: Path,
    cfg: Config,
    progress: ProgressFn | None = None,
    force: bool = False,
) -> AnalysisResult:
    work_dir.mkdir(parents=True, exist_ok=True)
    fp = fingerprint(video, cfg)
    if not force:
        cached = load_cached(work_dir, fp)
        if cached is not None:
            log.info("analysis cache hit for %s", video.title)
            if progress:
                progress(1.0, "Loaded cached analysis")
            return cached.model_copy(
                update={
                    "video": video,
                    "transcript": transcribe_mod.drop_hallucinations(cached.transcript, cfg.whisper.min_word_prob),
                }
            )

    stages = StageProgress(STAGES, progress)
    rate = cfg.analysis.rate_hz
    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    stages.report("audio", 0.0, "Extracting audio")
    has_audio = probe(video.path).has_audio
    curves: dict = {}
    events = []
    transcript = Transcript(backend="none")
    if has_audio:
        wav = audio_mod.extract_wav(video.path, work_dir / "audio.wav")
        stages.report("audio", 0.5, "Analyzing loudness and onsets")
        curves, events = audio_mod.analyze_audio(
            wav, video.duration, rate, cfg.analysis.silence_db, cfg.analysis.spike_z
        )
        timings["audio"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        stages.report("transcribe", 0.0, "Transcribing speech")
        cached_transcript = None if force else _load_transcript(work_dir, fp)
        if cached_transcript is not None:
            transcript = cached_transcript
            log.info("reusing transcript from an earlier (interrupted) run")
        else:
            try:
                transcript = transcribe_mod.transcribe(wav, cfg.whisper, cfg.analysis.sentence_pause_s)
                # Transcription is by far the slowest stage: persist it on its own so a killed run keeps it.
                _save_transcript(work_dir, fp, transcript)
            except Exception as exc:  # ASR is optional: fall back to signal-only analysis
                log.exception("transcription failed; continuing without transcript")
                transcript = Transcript(backend=f"failed: {type(exc).__name__}")
        timings["transcribe"] = time.perf_counter() - t0
    else:
        log.warning("%s has no audio stream; skipping audio + transcript", video.title)
        empty = [0.0] * (int(video.duration * rate) + 1)
        for name in ("audio_rms_db", "audio_rms_z", "audio_onset", "audio_band_z", "silence"):
            curves[name] = SignalCurve(name=name, rate_hz=rate, values=list(empty))
    stages.report("transcribe", 1.0, "Transcript ready")

    t0 = time.perf_counter()
    stages.report("scenes", 0.0, "Detecting scene cuts")
    try:
        cuts = scenes_mod.detect_scene_cuts(
            video.path, cfg.analysis.scene_adaptive_threshold, cfg.analysis.scene_min_len_s
        )
    except Exception as exc:
        raise AnalysisError(f"Scene detection failed: {exc}") from exc
    timings["scenes"] = time.perf_counter() - t0
    stages.report("scenes", 1.0, f"{len(cuts)} cuts")

    t0 = time.perf_counter()
    stages.report("motion", 0.0, "Measuring motion")
    motion_curve, centroids = motion_mod.analyze_motion(video.path, video.duration, rate)
    curves["motion"] = motion_curve
    timings["motion"] = time.perf_counter() - t0
    stages.report("motion", 1.0, "Motion done")

    event_curve, action_events = fuse_events(motion_curve, curves["audio_onset"], cuts, rate)
    curves["event"] = event_curve
    events = sorted(events + action_events, key=lambda e: e.time)
    stages.report("events", 1.0, f"{len(events)} events")

    result = AnalysisResult(
        fingerprint=fp,
        video=video,
        transcript=transcript,
        scene_cuts=cuts,
        curves=curves,
        events=events,
        motion_centroids=centroids,
        centroid_rate_hz=rate,
    )
    cache_path(work_dir).write_text(result.model_dump_json(), encoding="utf-8")
    log.info("analysis timings: %s", {k: round(v, 1) for k, v in timings.items()})
    # The cache keeps the raw transcript so a threshold change doesn't need whisper again.
    return result.model_copy(
        update={"transcript": transcribe_mod.drop_hallucinations(transcript, cfg.whisper.min_word_prob)}
    )
