"""Optional Claude pass: rewrite titles/hooks/descriptions and give an explainable virality score.

Only text goes to the API (clip transcript, signal summary, template draft). Video never leaves the
machine. Any failure falls back to the template draft so clip_video always completes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

from viral_clipper.config import Config, Profile
from viral_clipper.errors import LLMUnavailableError
from viral_clipper.metadata.platforms import apply_rules, rules_for
from viral_clipper.models import Candidate, ClipMetadata, Platform

log = logging.getLogger(__name__)


class PlatformCopy(BaseModel):
    platform: Platform
    title: str = Field(description="Title/caption within the platform's character limit.")
    description: str
    hashtags: list[str] = Field(description="Hashtags with the # prefix, within the platform's count limit.")


class ViralityScore(BaseModel):
    hook: int = Field(ge=0, le=100, description="Does the opening grab attention and relate to the topic?")
    flow: int = Field(ge=0, le=100, description="Logical progression and a satisfying ending?")
    value: int = Field(ge=0, le=100, description="Useful, funny or emotionally resonant?")
    trend: int = Field(ge=0, le=100, description="Fits current interests of the niche's audience?")
    overall: int = Field(ge=0, le=100)
    reason: str = Field(description="One sentence a creator can act on.")


class LLMBundle(BaseModel):
    hook: str = Field(description="1-3 second on-screen hook text, max 8 words.")
    platform_copy: list[PlatformCopy] = Field(description="One entry per requested platform.")
    virality: ViralityScore


def credentials_present() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    profile_dir = Path(os.path.expanduser("~/.config/anthropic"))
    return profile_dir.exists() and any(profile_dir.iterdir())


def llm_enabled(cfg: Config) -> bool:
    if cfg.llm.provider == "none":
        return False
    if cfg.llm.provider == "anthropic":
        if not credentials_present():
            raise LLMUnavailableError("llm.provider is 'anthropic' but no Anthropic credentials were found.")
        return True
    return credentials_present()


def _system_prompt(profile: Profile) -> str:
    return (
        "You write short-form video metadata for a clipping tool. Niche: "
        f"{profile.name} — {profile.description.strip()}\n"
        "Rules: hooks are curiosity gaps, shocks, 'wait for it', bold claims or open loops, never clickbait "
        "that the clip does not pay off. Titles are specific, use numbers from the transcript when present, "
        "no ALL CAPS sentences, no links. Hashtags mix 2-3 niche tags with generic reach tags and respect the "
        "per-platform limits given. Score virality on OpusClip's public rubric (Hook, Flow, Value, Trend) "
        "and explain in one sentence."
    )


def _user_prompt(
    cand: Candidate, video_title: str, draft_hook: str, draft: dict[Platform, ClipMetadata], platforms: list[Platform]
) -> str:
    limits = "\n".join(
        f"- {p.value}: title <= {rules_for(p).title_max} chars, "
        f"{rules_for(p).hashtag_min}-{rules_for(p).hashtag_max} hashtags. {rules_for(p).notes}"
        for p in platforms
    )
    signals = ", ".join(f"{k}={v:.2f}" for k, v in sorted(cand.features.items(), key=lambda kv: -kv[1])[:8])
    drafts = "\n".join(f"- {p.value}: title={m.title!r} hashtags={' '.join(m.hashtags)}" for p, m in draft.items())
    return (
        f"Source video title: {video_title}\n"
        f"Clip: {cand.start:.1f}s-{cand.end:.1f}s ({cand.duration:.0f}s). Signal score {cand.score:.0f}/100. "
        f"Reasons: {'; '.join(cand.reasons)}\nTop signals: {signals}\n"
        f"Hook pattern to use: {cand.hook_pattern}\n\n"
        f'Transcript of the clip:\n"""\n{cand.transcript_text or "(no speech — gameplay/action only)"}\n"""\n\n'
        f"Platform limits:\n{limits}\n\n"
        f"Template drafts to improve on (keep what works):\nhook={draft_hook!r}\n{drafts}\n\n"
        "Return the hook, one copy entry per platform listed, and the virality score."
    )


def refine_with_llm(
    cand: Candidate,
    video_title: str,
    profile: Profile,
    draft_hook: str,
    draft: dict[Platform, ClipMetadata],
    platforms: list[Platform],
    cfg: Config,
) -> tuple[str, dict[Platform, ClipMetadata], ViralityScore | None]:
    """Returns (hook, metadata, virality). On any failure returns the draft unchanged."""
    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=cfg.llm.model,
            max_tokens=cfg.llm.max_tokens,
            system=_system_prompt(profile),
            messages=[{"role": "user", "content": _user_prompt(cand, video_title, draft_hook, draft, platforms)}],
            output_format=LLMBundle,
        )
        if response.stop_reason == "refusal":
            log.warning("LLM declined clip %.1f-%.1f; keeping template metadata", cand.start, cand.end)
            return draft_hook, draft, None
        bundle = response.parsed_output
        if bundle is None:
            return draft_hook, draft, None
    except Exception as exc:  # network, auth, schema: all non-fatal
        log.warning("LLM metadata failed (%s: %s); keeping template metadata", type(exc).__name__, str(exc)[:200])
        return draft_hook, draft, None

    hook = bundle.hook.strip() or draft_hook
    out = dict(draft)
    for entry in bundle.platform_copy:
        if entry.platform not in platforms:
            continue
        title, description, tags = apply_rules(entry.platform, entry.title, entry.description, entry.hashtags)
        if len(tags) < rules_for(entry.platform).hashtag_min:
            tags = apply_rules(entry.platform, "", "", tags + draft[entry.platform].hashtags)[2]
        out[entry.platform] = ClipMetadata(
            platform=entry.platform, title=title, description=description, hashtags=tags, hook=hook
        )
    return hook, out, bundle.virality
