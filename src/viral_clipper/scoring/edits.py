"""Assemble a context-complete clip from one story: opening → stakes → build-up → payoff → reaction.

This follows how editors actually cut shorts (docs/research.md §6): pick the payoff first, choose the
opening and ending separately, pull in every line a newcomer needs (who these people are, what they
win or lose), then prune the filler between them so the result fits the length budget. The output is
an edit list of source ranges joined with jump cuts, not one contiguous window.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from viral_clipper.config import ClipConfig, Profile
from viral_clipper.models import AnalysisResult, Candidate, Segment, StoryInfo
from viral_clipper.scoring.candidates import Window, select_non_overlapping
from viral_clipper.scoring.scorer import CONTINUATION_RE, PRONOUN_START_RE, Scorer, score_moments
from viral_clipper.scoring.signals import SignalContext
from viral_clipper.scoring.stories import Story, StoryModel, Unit, build_story_model, format_amount, pick_payoffs

log = logging.getLogger(__name__)

REACTION_S = 6.0  # keep this much after the payoff, then stop: every second past the beat costs viewers
ACTION_LEAD_S = 6.0  # a speechless payoff keeps this much build-up before its peak
LEAD_PAD_S = 0.12  # padding before the first word of a kept sentence
TAIL_PAD_S = 0.2  # and after its last word
MIN_SEGMENT_S = 0.3


@dataclass
class EditPlan:
    story: Story
    payoff: Unit
    units: list[Unit]  # kept units, chronological
    segments: list[Segment]
    premise: str
    names: list[str]
    stakes_text: str
    coverage: float
    coverage_detail: str
    core: tuple[float, float]
    is_final: bool = False  # the story's last payoff: its result, the most complete clip it can give

    @property
    def duration(self) -> float:
        return sum(s.duration for s in self.segments)


# --- unit → segments ------------------------------------------------------------------------------


def _peak_time(ctx: SignalContext, a: float, b: float) -> float:
    arr = ctx.window(ctx.event, a, b) + ctx.window(ctx.audio_z, a, b)
    return a + (int(np.argmax(arr)) / ctx.rate_hz if arr.size else 0.0)


class WordBounds:
    """Neighbouring-word lookup so padding never lets the next sentence's first syllable leak in."""

    def __init__(self, ctx: SignalContext) -> None:
        words = ctx.transcript.words
        self.starts = np.array([w.start for w in words], dtype=float)
        self.ends = np.array([w.end for w in words], dtype=float)

    def pad(self, a: float, b: float) -> tuple[float, float]:
        i = int(np.searchsorted(self.ends, a + 1e-3, side="right")) - 1
        prev_end = self.ends[i] if i >= 0 and self.ends[i] <= a + 1e-3 else -1e9
        j = int(np.searchsorted(self.starts, b - 1e-3, side="left"))
        next_start = self.starts[j] if j < len(self.starts) else 1e9
        lead = max(0.0, min(LEAD_PAD_S, a - prev_end - 0.03))
        tail = max(0.0, min(TAIL_PAD_S, next_start - b - 0.03))
        return a - lead, b + tail


def unit_segments(
    u: Unit, ctx: SignalContext, max_pause: float, is_payoff: bool = False, bounds: WordBounds | None = None
) -> list[tuple[float, float]]:
    """Source ranges for one unit with long pauses inside it cut out."""
    if u.kind == "action":
        a, b = u.start, u.end
        if b - a > ACTION_LEAD_S + 2.0:
            peak = _peak_time(ctx, a, b)
            a = max(a, peak - ACTION_LEAD_S)
            b = min(b, peak + (2.0 if not is_payoff else 3.0))
        return [(a, b)] if b - a >= MIN_SEGMENT_S else []
    words = u.words
    if not words:
        return [(u.start, u.end)]
    if u.cue_word and u.cue_word < len(words):
        # Mid-sentence transition: drop the tail of the previous segment ("That was sick, but …").
        words = words[u.cue_word :]
    out: list[tuple[float, float]] = []
    seg_start = words[0].start
    prev_end = words[0].end
    for w in words[1:]:
        if w.start - prev_end > max_pause:
            out.append((seg_start, prev_end))
            seg_start = w.start
        prev_end = w.end
    out.append((seg_start, prev_end))
    if bounds is None:
        return [(a - LEAD_PAD_S, b + TAIL_PAD_S) for a, b in out if b - a >= 0.05]
    return [bounds.pad(a, b) for a, b in out if b - a >= 0.05]


def merge_segments(parts: list[tuple[float, float]], max_gap: float, duration: float) -> list[tuple[float, float]]:
    parts = sorted((max(0.0, a), min(duration, b)) for a, b in parts if b > a)
    merged: list[tuple[float, float]] = []
    for a, b in parts:
        if merged and a - merged[-1][1] <= max_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return [(a, b) for a, b in merged if b - a >= MIN_SEGMENT_S]


# --- story context --------------------------------------------------------------------------------


def _display(name: str, model: StoryModel) -> str:
    form = model.name_display.get(name, name.title())
    return form if len(form) <= 14 else form.split()[-1]


def _clean_start(u: Unit) -> float:
    if u.cue:
        return 1.0
    first = u.text.strip().split()[0].strip("\"'“”(,.") if u.text.strip() else ""
    if CONTINUATION_RE.match(first):
        return 0.0
    if PRONOUN_START_RE.match(first):
        return 0.5
    return 1.0


def _scope(model: StoryModel, story: Story) -> list[Unit]:
    """The story's units, plus the units of the stories it continues.

    A story that was split only because it ran long (no spoken transition at its start) still needs
    the setup from the part before it.
    """
    units = list(story.units)
    i = story.index
    while model.stories[i].continued and i > 0:
        i -= 1
        units = list(model.stories[i].units) + units
        if story.end - model.stories[i].start > 600:
            break
    return units


def _premise(names: list[str], amounts: list[int], stakes_text: str) -> str:
    amt = format_amount(max(amounts)) if amounts else ""
    short = " ".join(stakes_text.split()) if stakes_text and len(stakes_text.split()) <= 10 else ""
    if len(names) >= 2 and amt:
        return f"{names[0]} vs {names[1]} for {amt}"
    if short:
        return short
    if len(names) == 1 and amt:
        return f"{names[0]} plays for {amt}"
    if len(names) >= 2:
        return f"{names[0]} vs {names[1]}"
    return ""


# --- assembly -------------------------------------------------------------------------------------


def build_edit(
    model: StoryModel,
    story: Story,
    payoff_pos: int,
    ctx: SignalContext,
    clip: ClipConfig,
    min_len: float,
    max_len: float,
    target: float,
    duration: float,
) -> EditPlan | None:
    scope = _scope(model, story)
    payoff = story.units[payoff_pos]
    p_at = next(i for i, u in enumerate(scope) if u is payoff)
    ads = {u.index for u in scope if u.is_ad}

    # Ending: the payoff plus its reaction, cut REACTION_S after the payoff ends.
    reaction: list[Unit] = []
    for u in scope[p_at + 1 :]:
        if u.cue or u.teaser or u.start > payoff.end + REACTION_S or u.index in ads:
            break
        if u.is_filler and reaction:
            break  # "Yeah." after the reaction is the wind-down: end on the reaction instead
        # A line about someone outside this story is the hand-off to the next segment.
        if u.names and not (u.names & set(story.names)):
            break
        reaction.append(u)

    before = [u for u in scope[:p_at] if u.index not in ads]
    if not before:
        return None
    # Opening: the latest spoken transition that still leaves room for a setup; else the first clean line.
    cue_units = [u for u in before if u.cue and u.start <= payoff.start - 8.0]
    if cue_units:
        opening = cue_units[-1]
    else:
        speech = [u for u in before if u.kind == "speech" and not u.is_filler]
        opening = next((u for u in speech if _clean_start(u) == 1.0), speech[0] if speech else before[0])
    body = [u for u in before if u.start >= opening.start]

    stakes_units = sorted(
        (u for u in body if u.stakes >= 0.5), key=lambda u: (-(u.stakes + (0.5 if u.amounts else 0.0)), u.start)
    )[:2]
    # Build-up right before the payoff: the last spoken line and any action leading into it.
    lead_in: list[Unit] = []
    for u in reversed(body):
        if u is opening:
            break
        lead_in.append(u)
        if u.kind == "speech" and not u.is_filler:
            break

    required: dict[int, str] = {opening.index: "opening", payoff.index: "payoff"}
    for u in stakes_units:
        required.setdefault(u.index, "stakes")
    for u in lead_in:
        required.setdefault(u.index, "escalation")
    for u in reaction:
        required.setdefault(u.index, "reaction")

    # Who is this about? Main names = mentioned at least twice in the story, or in the payoff/reaction.
    end_units = [payoff, *reaction]
    main = {n for n, c in story.names.items() if c >= 2} | {n for u in end_units for n in u.names if not u.teaser}
    used = {n for i in required for n in model.units[i].names} & main
    intro_units: list[Unit] = []
    explained = {n for i in required for n in model.units[i].names if model.units[i].start <= payoff.start}
    for name in sorted(used - explained):
        first = next((u for u in body if name in u.names), None)
        if first is None:
            # An intro from far earlier in the video would feel random; the premise card names them instead.
            idx = model.first_mention.get(name)
            first = model.units[idx] if idx is not None and model.units[idx].start >= story.start - 120 else None
        if first is not None and first.duration <= clip.max_context_splice_s and first.index not in ads:
            intro_units.append(first)
    for u in intro_units:
        required.setdefault(u.index, "context")

    bounds = WordBounds(ctx)

    def seg_of(u: Unit) -> list[tuple[float, float]]:
        return unit_segments(u, ctx, clip.max_pause_s, is_payoff=u is payoff, bounds=bounds)

    def total(indices: dict[int, str]) -> float:
        parts = [p for i in indices for p in seg_of(model.units[i])]
        return sum(b - a for a, b in merge_segments(parts, clip.max_pause_s, duration))

    # Over budget even before optional lines: shed the cheapest context first.
    drop_order = [u.index for u in intro_units if u.start < story.start] + [u.index for u in stakes_units[1:]]
    drop_order += [u.index for u in lead_in if u.kind == "action"]
    drop_order += [u.index for u in reaction[2:]]
    for idx in drop_order:
        if total(required) <= max_len:
            break
        required.pop(idx, None)
    # Still too long: enter later (drop the earliest required lines, never the payoff or its build-up).
    for u in sorted((model.units[i] for i in list(required)), key=lambda u: u.start):
        if total(required) <= max_len:
            break
        if required.get(u.index) in ("opening", "stakes", "context") and u.start < payoff.start - 10:
            required.pop(u.index)
    if total(required) > max_len:
        return None

    # Optional lines between opening and payoff, most useful first; the closer to the payoff the better.
    keyword_names = set(main)
    optional: list[tuple[float, Unit]] = []
    for u in body:
        if u.index in required or u.index in ads or u.is_filler:
            continue
        near = 1.0 if payoff.start - u.end <= 30 else 0.0
        imp = (
            0.3 * (1.0 if u.names & keyword_names else 0.0)
            + 0.25 * (1.0 if u.amounts or any(ch.isdigit() for ch in u.text) else 0.0)
            + 0.25 * min(1.0, u.signal)
            + 0.2 * (1.0 if u.stakes > 0 or u.payoff_words > 0 else 0.0)
            + 0.25 * near
        )
        if u.kind == "action":
            imp = 0.8 * u.signal + 0.15 * near
        optional.append((imp, u))
    optional.sort(key=lambda t: -t[0])
    for imp, u in optional:
        cur = total(required)
        if cur >= target and imp < 0.6:
            break
        if total({**required, u.index: "body"}) <= max_len:
            required[u.index] = "escalation" if u.start > payoff.start - 30 else "body"
    if total(required) < min_len:
        # Short story: keep its quieter lines too, nearest to the payoff first.
        rest = [u for u in body if u.index not in required and u.index not in ads]
        for u in sorted(rest, key=lambda u: payoff.start - u.end):
            if total({**required, u.index: "body"}) > max_len:
                continue
            required[u.index] = "body"
            if total(required) >= min_len:
                break
    if total(required) < min_len:
        return None

    kept = sorted((model.units[i] for i in required), key=lambda u: u.start)
    raw = [p for u in kept for p in seg_of(u)]
    merged = merge_segments(raw, clip.max_pause_s, duration)
    segments: list[Segment] = []
    for a, b in merged:
        roles = [required[u.index] for u in kept if u.start < b and u.end > a]
        role = next((r for r in ("payoff", "reaction", "stakes", "opening", "context") if r in roles), "escalation")
        segments.append(Segment(start=round(a, 3), end=round(b, 3), role=role))

    # Context and the premise card.
    stakes_kept = [u for u in kept if required[u.index] in ("stakes", "opening") and u.stakes >= 0.5]
    stakes_text = stakes_kept[0].text if stakes_kept else (stakes_units[0].text if stakes_units else "")
    setup_units = [u for u in kept if u.start < payoff.start]
    order: list[str] = []
    for u in setup_units:
        for n in sorted(u.names, key=lambda n: u.text.lower().find(n)):
            if n in main and n not in order:
                order.append(n)
    # The premise card names the two people the story is about, even if their intro line was cut.
    for n in sorted(main, key=lambda n: -story.names.get(n, 0)):
        if n not in order and story.names.get(n, 0) >= 3:
            order.append(n)
    order.sort(key=lambda n: -story.names.get(n, 0))
    names = [_display(n, model) for n in order[:2]]
    amounts = [a for u in setup_units if u.stakes >= 0.5 or u is opening for a in u.amounts]
    premise = _premise(names, amounts, stakes_text)

    coverage, detail = _coverage(kept, required, payoff, main, premise, story, model)
    # The core is the part no other clip may reuse: the build-up into this payoff and what follows it.
    core_start = min([payoff.start, *(u.start for u in lead_in if u.index in required)])
    core_end = max(s.end for s in segments)
    return EditPlan(
        story=story,
        payoff=payoff,
        units=kept,
        segments=segments,
        premise=premise,
        names=names,
        stakes_text=stakes_text,
        coverage=coverage,
        coverage_detail=detail,
        core=(core_start, core_end),
        is_final=all(
            v.payoff_words == 0 and v.signal < payoff.signal for v in story.units[payoff_pos + len(reaction) + 1 :]
        ),
    )


def _coverage(
    kept: list[Unit], roles: dict[int, str], payoff: Unit, main: set[str], premise: str, story: Story, model: StoryModel
) -> tuple[float, str]:
    """1.0 = a stranger gets who, what's at stake, the payoff and a clean ending from the clip alone."""
    speech = [u for u in kept if u.kind == "speech"]
    open_ok = _clean_start(speech[0]) if speech else 0.5
    story_has_stakes = any(u.stakes >= 0.5 for u in story.units)
    has_stakes = any(u.stakes >= 0.5 for u in kept if u.start < payoff.start) or "$" in premise
    stakes_ok = 1.0 if has_stakes else (0.5 if not story_has_stakes else 0.0)
    clip_names = {n for u in kept for n in u.names} & main
    premise_lower = premise.lower()
    explained = {
        n for n in clip_names if any(n in u.names for u in kept if u.start <= payoff.start) or n in premise_lower
    }
    names_ok = len(explained) / len(clip_names) if clip_names else 1.0
    payoff_ok = 1.0 if (payoff.signal >= 0.3 or payoff.payoff_words > 0) else 0.5
    last = kept[-1]
    end_ok = (
        1.0
        if (
            last.kind == "action" or roles.get(last.index) == "reaction" or last.text.rstrip().endswith((".", "!", "?"))
        )
        else 0.5
    )
    score = 0.25 * open_ok + 0.2 * stakes_ok + 0.2 * names_ok + 0.2 * payoff_ok + 0.15 * end_ok
    bits = []
    if names_ok == 1.0 and clip_names:
        bits.append("who: " + ", ".join(sorted(_display(n, model) for n in clip_names)[:3]))
    if has_stakes:
        bits.append("stakes set up")
    if open_ok < 1.0:
        bits.append("opens mid-thought")
    if stakes_ok == 0.0:
        bits.append("stakes missing")
    if names_ok < 1.0:
        bits.append("some names unexplained")
    bits.append("payoff + reaction" if end_ok == 1.0 else "ends abruptly")
    return round(score, 3), "story: " + "; ".join(bits)


# --- candidates -----------------------------------------------------------------------------------


def edit_candidate(plan: EditPlan, scorer: Scorer, cold_open_s: float = 0.0) -> Candidate:
    parts = [(s.start, s.end) for s in plan.segments]
    segments = list(plan.segments)
    if cold_open_s > 0:
        peak = (
            plan.payoff.start
            if plan.payoff.kind == "speech"
            else _peak_time(scorer.ctx, plan.payoff.start, plan.payoff.end)
        )
        a = max(0.0, peak - cold_open_s / 2)
        segments = [Segment(start=round(a, 3), end=round(a + cold_open_s, 3), role="cold_open"), *segments]
        parts = [(a, a + cold_open_s), *parts]
    window = Window(
        start=parts[0][0],
        end=max(b for _a, b in parts),
        on_sentences=True,
        segments=tuple(parts),
        context=(plan.coverage, plan.coverage_detail),
    )
    cand = scorer.score_window(window)
    if plan.is_final:
        # A story's result beats its midpoints: the viewer gets the whole arc.
        cand.score = round(min(100.0, cand.score + 4.0), 1)
    span = plan.segments[-1].end - plan.segments[0].start
    removed = max(0.0, span - plan.duration)
    cand.segments = segments
    cand.start = round(min(s.start for s in segments), 2)
    cand.end = round(max(s.end for s in segments), 2)
    cand.core_start, cand.core_end = plan.core
    cand.peak_time = round(plan.payoff.start if plan.payoff.kind == "speech" else cand.peak_time, 2)
    cand.story = StoryInfo(
        story_index=plan.story.index,
        story_start=round(plan.story.start, 2),
        story_end=round(plan.story.end, 2),
        premise=plan.premise,
        names=plan.names,
        stakes=plan.stakes_text,
        payoff_time=round(plan.payoff.start, 2),
        removed_s=round(removed, 1),
    )
    summary = f"{len(segments)} cuts, {removed:.0f}s of filler removed" if len(segments) > 1 else "one continuous take"
    cand.reasons = [plan.coverage_detail, f"{summary}", *[r for r in cand.reasons if not r.startswith("story:")]][:5]
    return cand


def score_stories(
    result: AnalysisResult,
    profile: Profile,
    num_clips: int,
    min_len: float,
    max_len: float,
    clip: ClipConfig,
) -> tuple[list[Candidate], list[Candidate], StoryModel]:
    """Story-mode selection. Returns (selected, every story edit, the story model).

    When the video has fewer stories than requested clips, the rest are filled with the best
    contiguous windows that don't overlap a chosen story's core.
    """
    model = build_story_model(result, profile, max(clip.story_min_s, min_len * 0.66))
    scorer = Scorer(result, profile)
    target = float(np.clip(profile.length_prior.mean_s, min_len, max_len))
    edits: list[Candidate] = []
    for story in model.stories:
        speech = [u for u in story.units if u.kind == "speech"]
        if speech and sum(1 for u in speech if u.is_ad) > 0.5 * len(speech):
            log.info("story %d (%.0f-%.0fs) looks like a sponsor read; skipped", story.index, story.start, story.end)
            continue
        for pos in pick_payoffs(story):
            plan = build_edit(model, story, pos, scorer.ctx, clip, min_len, max_len, target, result.video.duration)
            if plan is not None:
                edits.append(edit_candidate(plan, scorer, clip.cold_open_s))
    edits.sort(key=lambda c: c.score, reverse=True)
    eligible = [c for c in edits if c.features.get("context_completeness", 1.0) >= clip.min_context]
    selected = select_non_overlapping(eligible, num_clips, clip.min_gap_s)
    if len(selected) < num_clips:
        windows, _ = score_moments(
            result,
            profile,
            num_clips * 3,
            min_len,
            max_len,
            clip.pre_roll_s,
            clip.post_roll_s,
            clip.min_gap_s,
            clip.min_context,
        )
        fill = select_non_overlapping(windows, num_clips - len(selected), clip.min_gap_s, taken=selected)
        selected = sorted(selected + fill, key=lambda c: c.score, reverse=True)
    return selected, edits, model
