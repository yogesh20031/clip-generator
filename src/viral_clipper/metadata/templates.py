"""Deterministic titles, hooks, descriptions and hashtags from the niche profile.

This is the always-available path: no API key, no network. It fills {placeholders} from what the
clip actually says (numbers, money, keyword hits, capitalized names) and falls back to the
profile's placeholder lists. Claude Code can rewrite any of it afterwards via set_clip_metadata.
"""

from __future__ import annotations

import re

from viral_clipper.config import Profile
from viral_clipper.metadata.platforms import apply_rules
from viral_clipper.models import Candidate, ClipMetadata, Platform
from viral_clipper.scoring.scorer import MONEY_RE

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
_NUMBER_RE = re.compile(r"\b\d[\d,]*\b")
_NAME_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")
_STOP = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "have",
    "from",
    "they",
    "what",
    "your",
    "about",
    "just",
    "like",
    "there",
    "their",
    "would",
    "going",
    "gonna",
    "really",
    "right",
    "yeah",
    "okay",
    "because",
    "think",
    "know",
    "want",
    "were",
    "been",
    "then",
    "them",
    "when",
    "which",
    "where",
    "here",
    "these",
    # Capitalized in transcripts but never a person's name.
    "all",
    "but",
    "yes",
    "wait",
    "guys",
    "bro",
    "dude",
    "man",
    "look",
    "listen",
    "today",
    "now",
    "wow",
    "nope",
    "alright",
    "hey",
    "hello",
    "come",
    "lets",
    "let's",
    "stop",
    "thank",
    "thanks",
    "sorry",
    "please",
    "welcome",
    "ladies",
    "gentlemen",
    "everyone",
    "everybody",
    "one",
    "two",
    "three",
    "four",
    "five",
    "ten",
    "hundred",
    "thousand",
    "million",
    "dollars",
    "mystery",
}


def _proper_names(text: str) -> list[str]:
    """Capitalized words that are not sentence-initial (whisper capitalizes names and sentence starts)."""
    tokens = text.split()
    names: list[str] = []
    for i, tok in enumerate(tokens):
        word = tok.strip("\"'“”.,!?()")
        if not _NAME_RE.fullmatch(word) or word.lower() in _STOP:
            continue
        sentence_start = i == 0 or tokens[i - 1].rstrip("\"'”)").endswith((".", "!", "?"))
        if not sentence_start:
            names.append(word)
    return names


class TemplateEngine:
    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self._kw = [re.compile(r"\b" + re.escape(k.lower()) + r"\w*", re.IGNORECASE) for k in profile.keywords]
        self._kw_names = list(profile.keywords)

    # --- placeholder extraction ------------------------------------------------------------

    def extract_values(self, cand: Candidate) -> dict[str, str]:
        text = cand.transcript_text
        values: dict[str, str] = {}
        amounts = [m for m in MONEY_RE.findall(text) if any(ch.isdigit() for ch in m)]
        numbers = _NUMBER_RE.findall(text)
        if amounts:
            values["amount"] = amounts[0].lstrip("$").strip()
            values["high"] = values["amount"]
        if numbers:
            values["n"] = numbers[0]
            values["seconds"] = numbers[0]
            if len(numbers) > 1:
                values["low"] = numbers[-1]
        names = _proper_names(text)
        if names:
            values["person"] = names[0]
        hits = [self._kw_names[i] for i, p in enumerate(self._kw) if p.search(text)]
        if hits:
            values["topic"] = hits[0]
            values["event"] = hits[0]
            values["mechanic"] = hits[0]
            values["feature"] = hits[0]
        else:
            salient = sorted(
                {w.strip(".,!?\"'").lower() for w in text.split() if len(w) > 5 and w.lower() not in _STOP},
                key=len,
                reverse=True,
            )
            if salient:
                values["topic"] = salient[0]
        values["t"] = str(max(1, int(cand.peak_time - cand.start)))
        return values

    def fill(self, template: str, values: dict[str, str], seed: int) -> str:
        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            if key in values:
                return values[key]
            options = self.profile.placeholders.get(key)
            if options:
                return options[seed % len(options)]
            return ""

        text = _PLACEHOLDER_RE.sub(repl, template)
        text = re.sub(r"\s{2,}", " ", text).replace(" …", "…").strip(" -:")
        return text

    # --- pieces ------------------------------------------------------------------------------

    def hook(self, cand: Candidate, seed: int) -> str:
        pool = [t for t in self.profile.hook_templates if t.pattern == cand.hook_pattern] or self.profile.hook_templates
        template = pool[seed % len(pool)]
        return self.fill(template.text, self.extract_values(cand), seed)

    def title(self, cand: Candidate, seed: int) -> str:
        values = self.extract_values(cand)
        template = self.profile.title_templates[seed % len(self.profile.title_templates)]
        title = self.fill(template, values, seed)
        if len(title) < 8:  # a template that lost all its placeholders
            title = self.quote_title(cand) or "Wait For It"
        return title

    def quote_title(self, cand: Candidate) -> str:
        """A short punchy sentence from the clip itself, if there is one."""
        sentences = re.split(r"(?<=[.!?])\s+", cand.transcript_text)
        good = [s.strip().strip('"') for s in sentences if 12 <= len(s.strip()) <= 60]
        return f"“{good[0].rstrip('.')}”" if good else ""

    def summary(self, cand: Candidate, limit: int = 160) -> str:
        text = " ".join(cand.transcript_text.split())
        if len(text) <= limit:
            return text
        return text[: limit - 1].rsplit(" ", 1)[0] + "…"

    def hashtags(self, cand: Candidate, platform: Platform) -> list[str]:
        base = list(self.profile.hashtags.get(platform, []))
        content = [
            n
            for i, (p, n) in enumerate(zip(self._kw, self._kw_names, strict=True))
            if p.search(cand.transcript_text) and " " not in n
        ]
        extra = [f"#{c.lower()}" for c in content[:2]]
        # Niche tags first, content tags squeeze in before the generic tail.
        return base[:3] + extra + base[3:]

    def bundle(self, cand: Candidate, seed: int, platforms: list[Platform]) -> tuple[str, dict[Platform, ClipMetadata]]:
        hook = self.hook(cand, seed)
        title = self.title(cand, seed)
        out: dict[Platform, ClipMetadata] = {}
        for platform in platforms:
            tags = self.hashtags(cand, platform)
            description = self.profile.description_template.format(
                hook=hook, summary=self.summary(cand), hashtags=" ".join(tags)
            )
            t, d, h = apply_rules(platform, title, description, tags)
            if platform == Platform.TIKTOK:
                t = apply_rules(platform, f"{hook} {' '.join(h[:3])}", "", [])[0]
            out[platform] = ClipMetadata(platform=platform, title=t, description=d, hashtags=h, hook=hook)
        return hook, out
