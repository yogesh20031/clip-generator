"""config.yaml + profiles/*.yaml loading.

Resolution order for the main config: VIRAL_CLIPPER_CONFIG env var, else <project>/config.yaml,
then <project>/config.local.yaml is deep-merged on top if it exists (git-ignored, for personal tweaks).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from viral_clipper.errors import ProfileNotFoundError
from viral_clipper.models import ALL_PLATFORMS, Platform


def project_root() -> Path:
    """The repo folder (holds config.yaml, profiles/, assets/)."""
    return Path(__file__).resolve().parents[2]


def expand(path: str | Path) -> Path:
    """~ and env vars expanded; relative paths are relative to the project root."""
    p = Path(os.path.expandvars(os.path.expanduser(str(path))))
    return p if p.is_absolute() else project_root() / p


class PathsConfig(BaseModel):
    # Everything for one video (downloaded source, clips, json/csv) lives in output_dir/<slug>/.
    output_dir: str = "~/Desktop/viral-clipper"
    log_dir: str = "logs"
    font: str = "assets/fonts/Montserrat-ExtraBold.ttf"
    face_model: str = "assets/models/face_detection_yunet_2023mar.onnx"


class WhisperConfig(BaseModel):
    backend: Literal["auto", "mlx", "faster_whisper", "none"] = "auto"
    # "auto" picks large-v3-turbo on a GPU backend and "small" on CPU.
    model: str = "auto"
    device: Literal["auto", "cuda", "cpu"] = "auto"
    compute_type: str = "auto"
    language: str | None = None
    vad_filter: bool = True
    beam_size: int = 5


class AnalysisConfig(BaseModel):
    rate_hz: float = 4.0
    motion_width: int = 160
    scene_adaptive_threshold: float = 3.0
    scene_min_len_s: float = 0.6
    silence_db: float = -40.0
    sentence_pause_s: float = 0.6
    spike_z: float = 2.5


class ClipConfig(BaseModel):
    num_clips: int = 10
    min_len: float = 30.0
    max_len: float = 70.0
    min_gap_s: float = 2.0
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = "medium"
    audio_bitrate: str = "192k"
    loudness_i: float = -14.0
    loudness_tp: float = -1.0
    loudness_lra: float = 11.0
    # Seconds of lead-in / tail added around sentence boundaries.
    pre_roll_s: float = 0.3
    post_roll_s: float = 0.4


class CaptionConfig(BaseModel):
    enabled: bool = True
    words_per_line: int = 3
    font_size: int = 84
    text_color: str = "#FFFFFF"
    highlight_color: str = "#FFE600"
    stroke_color: str = "#000000"
    stroke_width: int = 8
    # Vertical centre of the caption block as a fraction of frame height (safe zone: 0.12-0.75).
    y_ratio: float = 0.68
    uppercase: bool = True
    hook_enabled: bool = True
    hook_duration_s: float = 2.0
    hook_font_size: int = 92
    hook_y_ratio: float = 0.24
    hook_color: str = "#FFFFFF"
    hook_box_color: str = "#000000B0"


class LLMConfig(BaseModel):
    # auto = anthropic when credentials are present, otherwise templates.
    provider: Literal["auto", "none", "anthropic"] = "auto"
    model: str = "claude-opus-5-5"
    max_tokens: int = 4096
    # Weight of the LLM virality score when fusing with signal score (0 disables fusion).
    fusion_weight: float = 0.6


class Config(BaseModel):
    paths: PathsConfig = Field(default_factory=PathsConfig)
    whisper: WhisperConfig = Field(default_factory=WhisperConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    clip: ClipConfig = Field(default_factory=ClipConfig)
    captions: CaptionConfig = Field(default_factory=CaptionConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    platforms: list[Platform] = Field(default_factory=lambda: list(ALL_PLATFORMS))
    default_niche: str = "generic"
    log_level: str = "INFO"

    @property
    def output_root(self) -> Path:
        return expand(self.paths.output_dir)

    @property
    def log_dir(self) -> Path:
        return expand(self.paths.log_dir)

    @property
    def font_path(self) -> Path:
        return expand(self.paths.font)

    @property
    def face_model_path(self) -> Path:
        return expand(self.paths.face_model)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping at the top level")
    return data


def load_config(path: str | Path | None = None) -> Config:
    if path is None:
        env_path = os.environ.get("VIRAL_CLIPPER_CONFIG")
        path = expand(env_path) if env_path else project_root() / "config.yaml"
    path = Path(path)
    data: dict[str, Any] = _read_yaml(path) if path.exists() else {}
    local = path.with_name("config.local.yaml")
    if local.exists():
        data = _deep_merge(data, _read_yaml(local))
    return Config.model_validate(data)


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()


# --- Niche profiles -------------------------------------------------------------------------


class HookTemplate(BaseModel):
    pattern: Literal["curiosity_gap", "shock", "wait_for_it", "bold_claim", "open_loop"]
    text: str


class LengthPrior(BaseModel):
    mean_s: float = 30.0
    std_s: float = 12.0


class Profile(BaseModel):
    name: str
    description: str = ""
    weights: dict[str, float]
    keywords: dict[str, float] = Field(default_factory=dict)
    violence_keywords: list[str] = Field(default_factory=list)
    length_prior: LengthPrior = Field(default_factory=LengthPrior)
    hook_templates: list[HookTemplate]
    title_templates: list[str]
    description_template: str = "{hook}\n\n{summary}\n\n{hashtags}"
    hashtags: dict[Platform, list[str]]
    # Fallback fillers for {placeholders} when the transcript has nothing suitable.
    placeholders: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("hashtags", mode="before")
    @classmethod
    def _fill_missing_platforms(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        return {p.value: list(value.get(p.value, [])) for p in ALL_PLATFORMS}


def profiles_dir() -> Path:
    return project_root() / "profiles"


def list_profiles() -> list[str]:
    return sorted(p.stem for p in profiles_dir().glob("*.yaml"))


@lru_cache(maxsize=16)
def load_profile(name: str) -> Profile:
    path = profiles_dir() / f"{name}.yaml"
    if not path.exists():
        raise ProfileNotFoundError(
            f"No niche profile named {name!r}.", hint=f"Available: {', '.join(list_profiles())}."
        )
    data = _read_yaml(path)
    data.setdefault("name", name)
    return Profile.model_validate(data)
