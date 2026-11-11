"""Per-platform metadata rules (sources in docs/research.md §1 and §4.3)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from viral_clipper.models import Platform


@dataclass(frozen=True)
class PlatformRules:
    label: str
    title_max: int
    description_max: int
    hashtag_min: int
    hashtag_max: int
    notes: str


RULES: dict[Platform, PlatformRules] = {
    Platform.YOUTUBE_SHORTS: PlatformRules(
        label="YouTube Shorts",
        title_max=100,
        description_max=5000,
        hashtag_min=3,
        hashtag_max=3,
        notes="YouTube shows the first 3 hashtags above the title and ignores all of them past 60; "
        "Shorts over 60 s with a Content ID claim are blocked.",
    ),
    Platform.TIKTOK: PlatformRules(
        label="TikTok",
        title_max=150,
        description_max=2200,
        hashtag_min=5,
        hashtag_max=10,
        notes="Caption doubles as title. Mix niche and generic tags (OpusClip data: viral clips average ~10).",
    ),
    Platform.INSTAGRAM_REELS: PlatformRules(
        label="Instagram Reels",
        title_max=125,
        description_max=2200,
        hashtag_min=3,
        hashtag_max=5,
        notes="Instagram reportedly caps hashtags at 5 (Dec 2025); no watermarks, borders or mostly-text frames.",
    ),
    Platform.FACEBOOK_REELS: PlatformRules(
        label="Facebook Reels",
        title_max=100,
        description_max=2200,
        hashtag_min=2,
        hashtag_max=5,
        notes="Meta: no links, minimal capitals, at most 5 hashtags.",
    ),
}


def rules_for(platform: Platform) -> PlatformRules:
    return RULES[platform]


def normalize_hashtag(tag: str) -> str:
    tag = re.sub(r"[^0-9A-Za-z_]", "", tag.strip().lstrip("#"))
    return f"#{tag}" if tag else ""


def apply_rules(platform: Platform, title: str, description: str, hashtags: list[str]) -> tuple[str, str, list[str]]:
    rules = rules_for(platform)
    seen: set[str] = set()
    clean: list[str] = []
    for tag in hashtags:
        norm = normalize_hashtag(tag)
        if norm and norm.lower() not in seen:
            seen.add(norm.lower())
            clean.append(norm)
    clean = clean[: rules.hashtag_max]
    title = _truncate(" ".join(title.split()), rules.title_max)
    description = description.strip()[: rules.description_max]
    return title, description, clean


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.-") + "…"
