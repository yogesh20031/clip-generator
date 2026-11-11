"""Shared data types. Everything that crosses a module boundary is one of these."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Platform(StrEnum):
    YOUTUBE_SHORTS = "youtube_shorts"
    TIKTOK = "tiktok"
    INSTAGRAM_REELS = "instagram_reels"
    FACEBOOK_REELS = "facebook_reels"


ALL_PLATFORMS: tuple[Platform, ...] = tuple(Platform)


class VideoInfo(BaseModel):
    path: str
    title: str
    slug: str
    duration: float
    width: int
    height: int
    fps: float
    source_url: str | None = None
    video_id: str | None = None


class Word(BaseModel):
    text: str
    start: float
    end: float
    prob: float = 1.0


class Sentence(BaseModel):
    text: str
    start: float
    end: float
    words: list[Word] = Field(default_factory=list)


class Transcript(BaseModel):
    language: str = "en"
    backend: str = "none"
    model: str = ""
    words: list[Word] = Field(default_factory=list)
    sentences: list[Sentence] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.words

    def words_between(self, start: float, end: float) -> list[Word]:
        return [w for w in self.words if w.start >= start - 0.05 and w.end <= end + 0.05]

    def text_between(self, start: float, end: float) -> str:
        return " ".join(w.text for w in self.words_between(start, end)).strip()


class SignalCurve(BaseModel):
    """A per-video signal sampled on a fixed grid. Values are raw; the scorer normalizes."""

    name: str
    rate_hz: float
    values: list[float]

    @property
    def duration(self) -> float:
        return len(self.values) / self.rate_hz

    def index(self, t: float) -> int:
        i = int(round(t * self.rate_hz))
        return max(0, min(len(self.values) - 1, i))

    def slice(self, start: float, end: float) -> list[float]:
        if not self.values:
            return []
        a = self.index(start)
        b = max(a + 1, self.index(end))
        return self.values[a:b]


class Event(BaseModel):
    """A fused 'something happened' spike (explosion / crash / shout proxy)."""

    time: float
    strength: float
    kind: str = "spike"


class AnalysisResult(BaseModel):
    fingerprint: str
    video: VideoInfo
    transcript: Transcript
    scene_cuts: list[float]
    curves: dict[str, SignalCurve]
    events: list[Event]
    motion_centroids: list[tuple[float, float]] = Field(default_factory=list)
    centroid_rate_hz: float = 4.0

    def curve(self, name: str) -> SignalCurve:
        return self.curves[name]


class FeatureContribution(BaseModel):
    name: str
    value: float
    weight: float
    contribution: float


class Candidate(BaseModel):
    start: float
    end: float
    score: float
    peak_time: float
    features: dict[str, float]
    contributions: list[FeatureContribution]
    reasons: list[str]
    transcript_text: str
    hook_pattern: str

    @property
    def duration(self) -> float:
        return self.end - self.start


class ClipMetadata(BaseModel):
    platform: Platform
    title: str
    description: str
    hashtags: list[str]
    hook: str


class ClipRecord(BaseModel):
    index: int
    path: str
    thumbnail_path: str
    srt_path: str
    start: float
    end: float
    duration: float
    score: float
    reasons: list[str]
    transcript_text: str
    hook: str
    hook_pattern: str
    metadata: dict[Platform, ClipMetadata]
    features: dict[str, float] = Field(default_factory=dict)
    analytics: dict[str, float] = Field(default_factory=dict)


class ClipVideoResult(BaseModel):
    video_title: str
    source: str
    output_dir: str
    clips_json: str
    clips_csv: str
    clips: list[ClipRecord]
    warnings: list[str] = Field(default_factory=list)
    timings_s: dict[str, float] = Field(default_factory=dict)


class SentenceSummary(BaseModel):
    text: str
    start: float
    end: float


class AnalysisSummary(BaseModel):
    video: VideoInfo
    transcript_backend: str
    sentences: list[SentenceSummary]
    scene_cuts: list[float]
    audio_peaks: list[Event]
    energy_curve_1hz: list[float]
    motion_curve_1hz: list[float]
    cache_path: str


class OutputEntry(BaseModel):
    video_title: str
    output_dir: str
    clips_json: str
    clip_count: int
    clips: list[ClipRecord]
