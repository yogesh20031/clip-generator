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


class Segment(BaseModel):
    """One piece of source footage in a clip's edit list (source-time seconds)."""

    start: float
    end: float
    role: str = "body"  # opening | stakes | context | escalation | action | payoff | reaction | cold_open | body

    @property
    def duration(self) -> float:
        return self.end - self.start


class StoryInfo(BaseModel):
    """What a viewer needs to follow the clip: who, what is at stake, and when the payoff lands."""

    story_index: int
    story_start: float
    story_end: float
    premise: str = ""
    names: list[str] = Field(default_factory=list)
    stakes: str = ""
    payoff_time: float = 0.0
    removed_s: float = 0.0  # filler/dead air cut out between story start and the clip's end


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
    # Non-contiguous edit list; empty means the single range start..end.
    segments: list[Segment] = Field(default_factory=list)
    story: StoryInfo | None = None
    # Overlap is judged on the core (escalation → reaction), so two clips may share a setup line.
    core_start: float | None = None
    core_end: float | None = None

    @property
    def parts(self) -> list[Segment]:
        return self.segments or [Segment(start=self.start, end=self.end)]

    @property
    def duration(self) -> float:
        return sum(s.duration for s in self.parts)

    @property
    def premise(self) -> str:
        return self.story.premise if self.story else ""


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
    # clip_NN.txt next to the clip: hook, title, hashtags and description for every platform.
    metadata_txt: str = ""
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
    thumbnail_time: float = 0.0
    thumbnail_alternatives: list[str] = Field(default_factory=list)
    # The edit list (source times) and the story context it was built from.
    segments: list[Segment] = Field(default_factory=list)
    story: StoryInfo | None = None
    # Fill in after publishing (views, viewed-vs-swiped, skip rate, CTR) to refit profile weights later.
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


class StorySentence(BaseModel):
    """One numbered line of a story. `id` is the transcript sentence index used by render_edit."""

    id: int | None  # None for a speechless action stretch
    start: float
    end: float
    text: str
    role: str  # transition | stakes | payoff | action | filler | sponsor | body


class StoryOverview(BaseModel):
    index: int
    start: float
    end: float
    premise: str
    names: list[str]
    sentences: list[StorySentence]
    # The automatic edit for each payoff in this story: what clip_video would cut.
    proposed_edits: list[list[Segment]]
    proposed_scores: list[float]


class StoryMap(BaseModel):
    video_title: str
    source: str
    stories: list[StoryOverview]


class OutputEntry(BaseModel):
    video_title: str
    output_dir: str
    clips_json: str
    clip_count: int
    clips: list[ClipRecord]
