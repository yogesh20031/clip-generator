"""Turn a window into features (0-1), a weighted 0-100 score, and human-readable reasons."""

from __future__ import annotations

import math
import re

import numpy as np

from viral_clipper.config import Profile
from viral_clipper.models import AnalysisResult, Candidate, FeatureContribution, Segment
from viral_clipper.scoring.candidates import Window, generate_windows, select_non_overlapping
from viral_clipper.scoring.signals import SignalContext

MONEY_RE = re.compile(
    r"\$\s?\d[\d,.]*|\b\d{1,3}(?:,\d{3})+\b|\b(?:dollars?|bucks|grand|thousand|million|billion|hundred)\b",
    re.IGNORECASE,
)
TWIST_RE = re.compile(
    r"\b(?:but|until|then|suddenly|however|except|instead|turns out|plot twist|little did|what happened next)\b",
    re.IGNORECASE,
)

HOOK_WINDOW_S = 3.0
VIOLENCE_WINDOW_S = 7.0
# A clip must carry its own context: no mid-thought starts, a setup before the payoff, a real ending.
CONTINUATION_RE = re.compile(
    r"^(?:and|but|so|because|cause|'cause|then|which|also|or|plus|anyway|that's why|like i said)\b", re.IGNORECASE
)
PRONOUN_START_RE = re.compile(r"^(?:he|she|it|they|him|her|them|this|that|these|those)\b", re.IGNORECASE)
MIN_SETUP_S = 8.0  # seconds of setup wanted before the payoff
CONTEXT_WORDS = 40  # words for a speech clip to count as "complete"


def _fmt_t(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _keyword_regex(profile: Profile) -> list[tuple[re.Pattern[str], str, float]]:
    out = []
    for phrase, weight in profile.keywords.items():
        pattern = re.compile(r"\b" + re.escape(phrase.lower()) + r"\w*", re.IGNORECASE)
        out.append((pattern, phrase, weight))
    return out


class Scorer:
    def __init__(self, result: AnalysisResult, profile: Profile) -> None:
        self.result = result
        self.profile = profile
        self.ctx = SignalContext.from_analysis(result)
        self._keywords = _keyword_regex(profile)
        self._violence = [
            re.compile(r"\b" + re.escape(k.lower()) + r"\w*", re.IGNORECASE) for k in profile.violence_keywords
        ]
        self._positive_weight = sum(w for w in profile.weights.values() if w > 0) or 1.0

    # --- features ----------------------------------------------------------------------------

    def _cat(self, arr: np.ndarray, parts: tuple[tuple[float, float], ...]) -> np.ndarray:
        if len(parts) == 1:
            return self.ctx.window(arr, *parts[0])
        return np.concatenate([self.ctx.window(arr, a, b) for a, b in parts])

    def _source_time(self, parts: tuple[tuple[float, float], ...], out_t: float) -> float:
        """Clip-time seconds → source seconds."""
        acc = 0.0
        for a, b in parts:
            if out_t <= acc + (b - a):
                return a + (out_t - acc)
            acc += b - a
        return parts[-1][1]

    def features(self, window: Window) -> tuple[dict[str, float], dict[str, str], float]:
        """Returns (features, detail strings for reasons, peak_time in source seconds)."""
        ctx = self.ctx
        parts = window.parts
        start = parts[0][0]
        dur = max(0.1, sum(b - a for a, b in parts))
        words = [w for a, b in parts for w in ctx.transcript.words_between(a, b)]
        text = " ".join(w.text for w in words).strip()
        lower = text.lower()
        f: dict[str, float] = {}
        detail: dict[str, str] = {}

        def inside(t: float) -> bool:
            return any(a <= t <= b for a, b in parts)

        audio_z = self._cat(ctx.audio_z, parts)
        motion = self._cat(ctx.motion, parts)
        event = self._cat(ctx.event, parts)
        silence = self._cat(ctx.silence, parts)
        level = self._cat(ctx.audio_level, parts)

        peak_idx = int(np.argmax(event + audio_z)) if event.size else 0
        peak_rel = peak_idx / max(1, len(event))
        peak_time = self._source_time(parts, peak_idx / ctx.rate_hz)
        peak_val = float((event + audio_z)[peak_idx]) if event.size else 0.0

        f["audio_peak"] = float(audio_z.max()) if audio_z.size else 0.0
        if f["audio_peak"] > 0.3:
            loud_t = self._source_time(parts, int(np.argmax(audio_z)) / ctx.rate_hz)
            detail["audio_peak"] = f"loudness spike at {_fmt_t(loud_t)}"

        f["motion_intensity"] = float(motion.mean()) if motion.size else 0.0
        detail["motion_intensity"] = "high on-screen motion"

        cuts_in = int(sum(((ctx.scene_cuts > a) & (ctx.scene_cuts < b)).sum() for a, b in parts))
        f["scene_cut_density"] = min(1.0, (cuts_in / (dur / 10.0)) / 3.0)
        detail["scene_cut_density"] = f"{cuts_in} scene cuts"

        top3 = np.sort(event)[-3:] if event.size else np.zeros(1)
        f["event_density"] = float(top3.mean())
        n_action = sum(1 for e in ctx.events if e.kind == "action" and inside(e.time))
        detail["event_density"] = f"{n_action} action spikes (motion+audio+cut)"

        wps = len(words) / dur
        wps_norm = min(1.0, wps / (2 * ctx.median_wps)) if ctx.median_wps > 0 else 0.0
        f["speech_excitement"] = 0.6 * wps_norm + 0.4 * (float(level.mean()) if level.size else 0.0)
        detail["speech_excitement"] = f"fast, loud speech ({wps:.1f} words/s)"

        n_laugh = sum(1 for e in ctx.events if e.kind == "laugh_shout" and inside(e.time))
        f["laughter_shout"] = min(1.0, n_laugh / 2.0)
        detail["laughter_shout"] = f"{n_laugh} shout/laugh bursts"

        hits: list[str] = []
        kw_score = 0.0
        for pattern, phrase, weight in self._keywords:
            n = len(pattern.findall(lower))
            if n:
                hits.append(phrase)
                kw_score += weight * min(n, 2)
        f["keyword_hits"] = min(1.0, kw_score / 3.0)
        detail["keyword_hits"] = "keywords: " + ", ".join(hits[:4]) if hits else ""

        money = MONEY_RE.findall(text)
        f["money_number_mentions"] = min(1.0, len(money) / 3.0)
        detail["money_number_mentions"] = (
            "mentions " + ", ".join(dict.fromkeys(m.strip() for m in money[:3])) if money else ""
        )

        twists = TWIST_RE.findall(lower)
        f["twist_connectives"] = min(1.0, len(twists) / 3.0)
        detail["twist_connectives"] = "story turn: " + ", ".join(dict.fromkeys(twists[:3])) if twists else ""

        if peak_val < 0.15:
            f["payoff_in_window"] = 0.0
        else:
            f["payoff_in_window"] = 1.0 if peak_rel >= 0.6 else 0.2 + 0.8 * (peak_rel / 0.6)
        detail["payoff_in_window"] = f"payoff lands at {_fmt_t(peak_time)}"

        hook_n = max(1, int(HOOK_WINDOW_S * ctx.rate_hz))
        combo = (audio_z + motion) / 2 if audio_z.size else np.zeros(1)
        window_mean = float(combo.mean()) if combo.size else 0.0
        hook_mean = float(combo[:hook_n].mean()) if combo.size else 0.0
        ratio = hook_mean / window_mean if window_mean > 1e-3 else 0.0
        f["hook_strength"] = float(np.clip((ratio - 0.5) / 1.5, 0.0, 1.0))
        detail["hook_strength"] = "strong opening 3 seconds"

        f["sentence_boundary_bonus"] = 1.0 if window.on_sentences else 0.3
        detail["sentence_boundary_bonus"] = "starts and ends on full sentences"

        prior = self.profile.length_prior
        f["length_prior"] = math.exp(-0.5 * ((dur - prior.mean_s) / prior.std_s) ** 2)
        detail["length_prior"] = f"{dur:.0f}s is a good length for this niche"

        f["silence_penalty"] = min(1.0, 2.0 * float(silence.mean())) if silence.size else 0.0
        detail["silence_penalty"] = f"{float(silence.mean()) * 100:.0f}% dead air"

        first7 = " ".join(w.text for w in words if w.start < self._source_time(parts, VIOLENCE_WINDOW_S)).lower()
        violent_first7 = any(p.search(first7) for p in self._violence)
        violent_any = any(p.search(lower) for p in self._violence)
        early_end = self._source_time(parts, VIOLENCE_WINDOW_S)
        early_event = any(e.kind == "action" and start <= e.time <= early_end and inside(e.time) for e in ctx.events)
        f["violence_first7s"] = 1.0 if violent_first7 else (0.5 if (violent_any and early_event) else 0.0)
        detail["violence_first7s"] = "violence in the first 7 s (YouTube ad rule)"

        if window.context is not None:
            f["context_completeness"], detail["context_completeness"] = window.context
        else:
            f["context_completeness"], detail["context_completeness"] = self._context(
                words, text, peak_rel * dur, peak_val, window.on_sentences
            )

        # v2 placeholders: present so weights can be tuned now, zero until detectors exist.
        for name in ("face_reaction", "ocr_banner", "audio_event_class", "llm_hook_flow_value_trend"):
            f.setdefault(name, 0.0)
        return f, detail, peak_time

    @staticmethod
    def _context(
        words: list, text: str, peak_offset_s: float, peak_val: float, on_sentences: bool
    ) -> tuple[float, str]:
        """How self-contained the clip is: 1.0 = a viewer needs nothing from outside the clip."""
        if not words:
            # Pure gameplay/action: context is visual; reward a setup before the peak and clean cut edges.
            setup = min(1.0, peak_offset_s / MIN_SETUP_S) if peak_val >= 0.15 else 0.6
            return round(0.5 + 0.5 * setup, 3), "action builds up before the payoff"
        first = words[0].text.strip("\"'“”(")
        start_ok = 0.0 if CONTINUATION_RE.match(first) else (0.5 if PRONOUN_START_RE.match(first) else 1.0)
        last = words[-1].text.rstrip("\"'”)")
        end_ok = 1.0 if last.endswith((".", "!", "?", "…")) else 0.4
        setup_ok = min(1.0, peak_offset_s / MIN_SETUP_S) if peak_val >= 0.15 else 0.6
        content_ok = min(1.0, len(words) / CONTEXT_WORDS)
        if not on_sentences:
            start_ok *= 0.5
            end_ok *= 0.5
        score = 0.35 * start_ok + 0.2 * end_ok + 0.25 * setup_ok + 0.2 * content_ok
        problems = []
        if start_ok < 1.0:
            problems.append(f"opens mid-thought ('{first}…')")
        if end_ok < 1.0:
            problems.append("ends without a full stop")
        if setup_ok < 0.6:
            problems.append("payoff arrives before any setup")
        if content_ok < 0.5:
            problems.append("too little speech to stand alone")
        detail = (
            "self-contained: setup, payoff and a clean ending" if not problems else "context: " + "; ".join(problems)
        )
        return round(score, 3), detail

    # --- scoring -----------------------------------------------------------------------------

    def score_window(self, window: Window) -> Candidate:
        feats, detail, peak_time = self.features(window)
        contributions: list[FeatureContribution] = []
        total = 0.0
        for name, weight in self.profile.weights.items():
            value = feats.get(name, 0.0)
            if name == "llm_hook_flow_value_trend" and value == 0.0:
                continue  # not available yet; don't dilute the score
            contribution = weight * value
            total += contribution
            contributions.append(FeatureContribution(name=name, value=value, weight=weight, contribution=contribution))
        score = 100.0 * max(0.0, min(1.0, total / self._positive_weight))
        reasons = [
            detail[c.name]
            for c in sorted(contributions, key=lambda c: c.contribution, reverse=True)
            if c.contribution > 0.02 and detail.get(c.name)
        ][:3]
        penalties = [detail[c.name] for c in contributions if c.contribution < -0.05 and detail.get(c.name)]
        reasons += [f"penalty: {p}" for p in penalties[:1]]
        parts = window.parts
        return Candidate(
            start=round(parts[0][0], 2),
            end=round(parts[-1][1], 2),
            score=round(score, 1),
            peak_time=round(peak_time, 2),
            features={k: round(v, 3) for k, v in feats.items()},
            contributions=contributions,
            reasons=reasons or ["balanced signals"],
            transcript_text=" ".join(self.ctx.transcript.text_between(a, b) for a, b in parts).strip(),
            hook_pattern=pick_hook_pattern(feats),
            segments=[Segment(start=round(a, 3), end=round(b, 3)) for a, b in window.segments],
        )


def pick_hook_pattern(f: dict[str, float]) -> str:
    """Map the signal shape of a window to one of the five proven hook patterns."""
    if f.get("payoff_in_window", 0) >= 0.9 and f.get("hook_strength", 0) < 0.5:
        return "wait_for_it"
    if f.get("hook_strength", 0) >= 0.6 and f.get("audio_peak", 0) >= 0.5:
        return "shock"
    if f.get("twist_connectives", 0) >= 0.3:
        return "open_loop"
    if f.get("money_number_mentions", 0) >= 0.3 or f.get("keyword_hits", 0) >= 0.4:
        return "curiosity_gap"
    return "bold_claim"


def score_moments(
    result: AnalysisResult,
    profile: Profile,
    num_clips: int,
    min_len: float,
    max_len: float,
    pre_roll: float,
    post_roll: float,
    min_gap: float,
    min_context: float = 0.35,
) -> tuple[list[Candidate], list[Candidate]]:
    """Returns (selected non-overlapping top clips, all scored candidates sorted by score).

    Rule: a clip must make sense on its own. Windows below `min_context` are dropped as long as enough
    self-contained windows remain to fill the request.
    """
    scorer = Scorer(result, profile)
    windows = generate_windows(result, min_len, max_len, pre_roll, post_roll)
    scored = [scorer.score_window(w) for w in windows]
    scored.sort(key=lambda c: c.score, reverse=True)
    eligible = [c for c in scored if c.features.get("context_completeness", 1.0) >= min_context]
    selected = select_non_overlapping(eligible, num_clips, min_gap)
    if len(selected) < num_clips:
        selected = select_non_overlapping(scored, num_clips, min_gap)
    return selected, scored
