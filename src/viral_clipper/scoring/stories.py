"""Split a video into stories and label each story's beats.

A clip has to be one complete story for someone who never saw the long video: who is involved,
what is at stake, the build-up, the payoff and the reaction (docs/research.md §6). This module finds
those stories in the transcript and labels every piece of them; scoring/edits.py then assembles a
condensed edit from the labelled units.

Story boundaries combine five cues at every gap between sentences: an explicit transition phrase
("it is finally time", "for our next 1v1"), a drop in lexical cohesion (TextTiling), a change in who
is being talked about, the pause length and a scene cut. Units are sentences plus "action gaps":
stretches with no speech but high motion/audio (a race, a shot, a crash), which often *are* the
payoff and must not be dropped as dead air.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from viral_clipper.config import Profile
from viral_clipper.models import AnalysisResult, Sentence, Word
from viral_clipper.scoring.signals import SignalContext

# --- phrase lists ---------------------------------------------------------------------------------

_CUES = [
    r"(?:but |and |okay,? |alright,? |all right,? )?(?:before that,? |for now,? |now,? |so,? |first,? )?"
    r"let'?s go (?:see|meet|hit|play|head|check|find|race|watch|visit)\b",
    r"(?:but |and |so,? )?let'?s (?:meet|head (?:over|to)|move on|check out|switch)\b",
    r"(?:it is|it's) (?:finally )?time\b",
    r"this time\b",
    r"(?:for |and )?(?:our|the) (?:next|first|final|last|second|third)\b",
    r"next(?: up)?\b",
    r"up next\b",
    r"starting with\b",
    r"now it'?s time\b",
    r"(?:round|challenge|level|game|day) (?:one|two|three|four|five|\d+)\b",
    r"welcome (?:to|back)\b",
    r"(?:and )?now,? we have\b",
    r"(?:and )?(?:up )?next,? (?:we have|is|up)\b",
    r"moving on\b",
    r"meanwhile\b",
    r"meet\b",
    r"say hello\b",
    r"in this video\b",
]
# Transitions that sit mid-sentence: "That was sick, but before that let's go see …".
_CUES_ANYWHERE = [
    r"\b(?:before that|for now),? let'?s (?:go |see |head |check )",
    r"\bbefore we (?:\w+ ){1,4}(?:let'?s|we'?re gonna|we are going to) (?:go|head|see)\b",
    r"\bwe'?re (?:gonna|going to) head (?:back )?(?:to|over)\b",
    r"\bfor our (?:next|final|last)\b",
    r"\bit is (?:finally )?time (?:to|for)\b",
]
_STAKES = [
    r"\bif (?:\w+ ){0,3}(?:wins?|beats?|loses?|can|makes?|hits?|survives?|finish(?:es)?)\b",
    r"\b(?:first|last) (?:one |person )?to\b",
    r"\bwhoever\b",
    r"\brules?\b",
    r"\bhead to head\b",
    r"\b1v1\b",
    r"\bprize\b",
    r"\bgoing to be (?:racing|competing|playing|going)\b",
    r"\b(?:give|win|keep|wire|donate) (?:\w+ ){0,3}(?:money|grand|dollars|prize)\b",
    r"\b\d+ (?:seconds|minutes|hours|days)\b",
    r"\bhandicap\b",
    r"\bhead start\b",
]
_PAYOFF = [
    r"\b(?:wins?|won|winner|winning)\b",
    r"\b(?:tie|tied)\b",
    r"\bmiss(?:ed)?\b",
    r"\beliminated\b",
    r"\bscored?\b",
    r"\bgoal\b",
    r"\b(?:lost|loses)\b",
    r"\b(?:made|did) it\b",
    r"\bno way\b",
    r"\bcongrat\w*",
    r"\bhere (?:is|are|'s)\b",
    r"\bit'?s over\b",
    r"\bgame over\b",
    r"\bchampion\b",
    r"\bbeat (?:him|her|them|you|me)\b",
    r"\boh my (?:god|gosh)\b",
]
_STOPWORDS = set(
    """a an the and or but so to of in on at for with from by as is are was were be been being it its this that
    these those i you he she we they me him her us them my your his our their what which who whom whose when where
    why how all any both each few more most other some such no nor not only own same than too very can will just
    don't should now yeah okay oh like gonna going get got go let's lets right know think want really here there
    one two three four five six seven eight nine ten one's that's it's i'm you're he's she's we're they're i've
    you've we've i'll you'll he'll she'll we'll they'll didn't doesn't isn't wasn't aren't weren't can't couldn't
    won't wouldn't haven't hasn't hadn't do does did done have has had say said bro guys man dude alright""".split()
)
# Capitalized mid-sentence by whisper but never the subject of a story.
_NOT_NAMES = {
    "god", "gosh", "technically", "honestly", "literally", "actually", "okay", "mister", "sir", "whoa",
    # Capitalized nouns that are places, brands or events, not the people a story is about.
    "derby", "bowl", "league", "hall", "fame", "olympic", "olympics", "instagram", "youtube", "tiktok", "shopify",
    "feastables", "foundation", "india", "indian", "american", "america", "britain", "british", "women", "men",
    "friends", "world", "cup", "championship", "series", "games", "team", "club", "beast", "channel", "christmas",
    "vegas", "city", "state", "university", "school", "street", "island", "beach", "run", "home", "little", "super",
    "major", "grand", "slam", "golden", "gold", "silver", "national", "international", "global", "family",
}  # fmt: skip
_LEAD_IN_RE = re.compile(r"\b(?:let'?s|we'?re (?:gonna|going to)|we are going to|it is|for our)\b")
_CUES_ANYWHERE_RES = [re.compile(p, re.IGNORECASE) for p in _CUES_ANYWHERE]
_TEASER_RE = re.compile(
    r"\b(?:later in (?:this|the) video|in this video|up next|next up|coming up|but before that|"
    r"so many more|stick around|stay tuned|wait until you (?:see|watch))\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-z][a-z']+")
_CAP_RE = re.compile(r"^[A-Z][a-z]{2,}$")

# Number words for spoken amounts ("a million dollars", "hundred grand").
_NUM_WORDS = {
    "a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
}  # fmt: skip
_SCALE = {"hundred": 100, "thousand": 1_000, "grand": 1_000, "k": 1_000, "million": 1_000_000, "billion": 1e9}
_AMOUNT_RE = re.compile(
    r"\$?\s?(\d[\d,.]*|a|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|hundred)"
    r"(?:\s+(hundred))?\s*(thousand|grand|million|billion|k)?\s*(dollars|bucks|grand)?",
    re.IGNORECASE,
)


def parse_amounts(text: str) -> list[int]:
    """Money amounts mentioned in speech: "$10,000", "100 grand", "a million dollars", "hundred grand"."""
    text = text.replace(" ,", ",")
    out: list[int] = []
    for m in _AMOUNT_RE.finditer(text):
        raw, hundred, scale, unit = m.group(1), m.group(2), m.group(3), m.group(4)
        has_dollar = m.group(0).lstrip().startswith("$")
        # "100 million people watching" is not money: millions need a $ or "dollars"; "grand" always is.
        if not (has_dollar or unit or (scale and scale.lower() == "grand")):
            continue
        if raw[0].isdigit():
            try:
                value = float(raw.replace(",", "").rstrip("."))
            except ValueError:
                continue
        else:
            value = float(_NUM_WORDS.get(raw.lower(), 0))
            if raw.lower() == "hundred":
                value = 100.0
        if hundred:
            value *= 100
        if scale:
            value *= _SCALE[scale.lower()]
        if unit and unit.lower() == "grand" and not scale:
            value *= 1_000
        if value >= 1:
            out.append(int(value))
    return out


def format_amount(value: int) -> str:
    if value >= 1_000_000:
        m = value / 1_000_000
        return f"${m:.0f}M" if m == int(m) else f"${m:.1f}M"
    if value >= 10_000:
        return f"${value // 1_000}K"
    return f"${value:,}"


# --- data -----------------------------------------------------------------------------------------


_AD_RE = re.compile(
    r"\b(?:sponsor\w*|free trial|link (?:is )?(?:below|in (?:the |my )?description)|sign up|promo code|use code|"
    r"discount|percent off|dot com|\w+\.com|app store|start (?:your|a) (?:own )?(?:business|store)|entrepreneurs?|"
    r"subscription|first sale|online store|check (?:them|it) out)\b",
    re.IGNORECASE,
)


def mark_ads(units: list[Unit], max_gap_s: float = 25.0) -> None:
    """Flag sponsor reads: lines with ad vocabulary, lines naming the advertised brand, and the gaps between."""
    hits = [u for u in units if u.kind == "speech" and _AD_RE.search(u.text)]
    if not hits:
        return
    brands = {n for u in hits for n in u.names}
    for u in units:
        if u in hits or (u.names & brands and any(abs(u.start - h.start) <= 90 for h in hits)):
            u.is_ad = True
    flagged = [u for u in units if u.is_ad]
    for a, b in zip(flagged, flagged[1:], strict=False):
        if b.start - a.end <= max_gap_s:
            for u in units[a.index + 1 : b.index]:
                u.is_ad = True


@dataclass
class Unit:
    """A sentence, or a speechless stretch of action, inside a story."""

    index: int
    start: float
    end: float
    kind: str  # speech | action
    text: str = ""
    words: list[Word] = field(default_factory=list)
    sentence_index: int | None = None
    signal: float = 0.0  # peak of event + loudness inside the unit, 0-1 scale of the video
    names: set[str] = field(default_factory=set)
    stakes: float = 0.0
    payoff_words: float = 0.0
    amounts: list[int] = field(default_factory=list)
    is_filler: bool = False
    cue: bool = False  # opens with a spoken transition ("for our next 1v1…")
    teaser: bool = False  # points at another part of the video ("later in this video", "but before that")
    # When the transition sits mid-sentence, the clip starts at this word ("let's see how an amateur…").
    cue_word: int = 0
    is_ad: bool = False  # part of a sponsor read; never kept
    role: str = "body"

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Story:
    index: int
    units: list[Unit]
    names: dict[str, int] = field(default_factory=dict)  # name -> mentions inside the story
    # True when the story was split off only for length: its setup lives in the story before it.
    continued: bool = False

    @property
    def start(self) -> float:
        return self.units[0].start

    @property
    def end(self) -> float:
        return self.units[-1].end

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class StoryModel:
    stories: list[Story]
    units: list[Unit]
    name_display: dict[str, str]  # key (last token) -> longest form seen ("Cristiano Ronaldo")
    first_mention: dict[str, int]  # name key -> unit index of its first mention in the video


# --- helpers --------------------------------------------------------------------------------------


def _compile(base: list[str], extra: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in [*base, *extra]]


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS and len(w) > 2]


def _name_vocabulary(sentences: list[Sentence]) -> dict[str, str]:
    """Names = capitalized words that are not sentence-initial somewhere in the video.

    Whisper capitalizes sentence starts and proper names, so a word that is capitalized mid-sentence
    is a name; once known, it also counts at the start of a sentence. Runs ("Cristiano Ronaldo") are
    keyed by their last token and displayed in their longest form.
    """
    from viral_clipper.metadata.templates import _STOP

    name_stop = _STOP | _NOT_NAMES

    display: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for s in sentences:
        tokens = s.text.split()
        run: list[str] = []
        for i, tok in enumerate(tokens + [""]):
            word = tok.strip("\"'“”.,!?():;")
            ok = bool(_CAP_RE.match(word)) and word.lower() not in name_stop and word.lower() not in _STOPWORDS
            if ok and i > 0:
                run.append(word)
            if not ok or tok.rstrip("\"'”)").endswith((".", "!", "?", ",")):
                run = [w for i2, w in enumerate(run) if i2 == 0 or w != run[i2 - 1]]
                if run:
                    key = run[-1].lower()
                    counts[key] += 1
                    form = " ".join(run)
                    if len(form) > len(display.get(key, "")):
                        display[key] = form
                run = []
    # "Tom" alone is the same person as "Tom Brady": fold first names into the full-name key.
    for key, form in list(display.items()):
        parts = form.split()
        if len(parts) >= 2 and parts[0].lower() in display and parts[0].lower() != key:
            display.pop(parts[0].lower(), None)
    return display


def _names_in(text: str, vocab: dict[str, str]) -> set[str]:
    found: set[str] = set()
    for tok in text.split():
        word = tok.strip("\"'“”.,!?():;").lower()
        if word.endswith("'s"):
            word = word[:-2]
        if word in _NOT_NAMES:
            continue
        if word in vocab:
            found.add(word)
        else:
            # "Cristiano" maps to the run keyed by "ronaldo".
            for key, form in vocab.items():
                if " " in form and word == form.split()[0].lower() and len(word) > 3:
                    found.add(key)
                    break
    return found


def _signal(ctx: SignalContext, start: float, end: float) -> float:
    seg = ctx.window(ctx.event, start, end) + ctx.window(ctx.audio_z, start, end)
    return float(seg.max()) / 2.0 if seg.size else 0.0


# --- units ----------------------------------------------------------------------------------------


def build_units(result: AnalysisResult, ctx: SignalContext, profile: Profile, min_action_s: float = 1.5) -> list[Unit]:
    sentences = result.transcript.sentences
    stakes_res = _compile(_STAKES, profile.stakes_words)
    payoff_res = _compile(_PAYOFF, profile.payoff_words)
    keyword_res = [re.compile(r"\b" + re.escape(k) + r"\w*", re.IGNORECASE) for k in profile.keywords]
    units: list[Unit] = []

    def add_action(a: float, b: float) -> None:
        if b - a < min_action_s:
            return
        motion = ctx.window(ctx.motion, a, b)
        event = ctx.window(ctx.event, a, b)
        audio = ctx.window(ctx.audio_z, a, b)
        silence = ctx.window(ctx.silence, a, b)
        busy = (
            (motion.size and float(np.percentile(motion, 75)) >= 0.45)
            or (event.size and float(event.max()) >= 0.5)
            or (audio.size and float(audio.max()) >= 0.35)
        )
        if busy and (not silence.size or float(silence.mean()) < 0.7):
            units.append(Unit(len(units), a, b, "action", signal=_signal(ctx, a, b)))

    prev_end = 0.0
    for si, s in enumerate(sentences):
        add_action(prev_end + 0.1, s.start - 0.1)
        text = s.text.strip()
        lower = text.lower()
        words = s.words or result.transcript.words_between(s.start, s.end)
        n_words = len(words) or len(text.split())
        u = Unit(
            len(units),
            s.start,
            s.end,
            "speech",
            text=text,
            words=list(words),
            sentence_index=si,
            signal=_signal(ctx, s.start, s.end),
            amounts=parse_amounts(text),
        )
        u.stakes = min(1.0, sum(1 for r in stakes_res if r.search(lower)) / 2.0 + (0.5 if u.amounts else 0.0))
        # "If Speed wins, …" sets up the stakes; it is not the moment someone wins.
        conditional = u.stakes >= 0.5 and re.search(r"\b(?:if|whoever|first to|last to)\b", lower) is not None
        u.payoff_words = min(1.0, sum(1 for r in payoff_res if r.search(lower)) / 1.5) * (0.2 if conditional else 1.0)
        has_kw = any(r.search(lower) for r in keyword_res)
        u.teaser = bool(_TEASER_RE.search(lower))
        u.is_filler = n_words < 4 and not u.amounts and not has_kw and u.signal < 0.35 and u.payoff_words == 0
        units.append(u)
        prev_end = s.end
    add_action(prev_end + 0.1, result.video.duration - 0.1)
    if not sentences:
        units.clear()
    return units


# --- segmentation ---------------------------------------------------------------------------------


def _boundary_scores(
    units: list[Unit], cuts: np.ndarray, cue_res: list[re.Pattern[str]], window_s: float = 25.0
) -> tuple[list[float], list[bool]]:
    """Score for a story boundary *before* each unit (index 0 is unused), and whether a spoken cue is there."""
    n = len(units)
    scores = [0.0] * n
    cues = [False] * n
    if n < 2:
        return scores, cues
    toks = [Counter(_tokens(u.text)) for u in units]
    starts = np.array([u.start for u in units])
    depth = np.zeros(n)
    name_shift = np.zeros(n)
    for i in range(1, n):
        t = units[i].start
        before = [j for j in range(i) if starts[j] >= t - window_s]
        after = [j for j in range(i, n) if starts[j] < t + window_s]
        a: Counter[str] = Counter()
        b: Counter[str] = Counter()
        for j in before:
            a.update(toks[j])
        for j in after:
            b.update(toks[j])
        keys = set(a) | set(b)
        if keys:
            va = np.array([a[k] for k in keys], dtype=float)
            vb = np.array([b[k] for k in keys], dtype=float)
            denom = np.linalg.norm(va) * np.linalg.norm(vb)
            depth[i] = 1.0 - (float(va @ vb) / denom if denom > 0 else 0.0)
        na = set().union(*(units[j].names for j in before)) if before else set()
        nb = set().union(*(units[j].names for j in after)) if after else set()
        if na and nb:
            name_shift[i] = 1.0 - len(na & nb) / len(na | nb)
        elif nb and not na:
            name_shift[i] = 0.7
    # Cohesion depth relative to this video: percentile rank.
    order = depth[1:].argsort().argsort()
    depth_pct = np.zeros(n)
    depth_pct[1:] = order / max(1, n - 2)
    for i in range(1, n):
        u = units[i]
        if u.kind != "speech":
            continue
        lower = u.text.strip().lower()
        cue = 1.0 if any(r.match(lower) for r in cue_res) else 0.0
        if not cue:
            hit = next((m for r in _CUES_ANYWHERE_RES if (m := r.search(lower))), None)
            if hit is not None:
                cue = 0.9
                lead = _LEAD_IN_RE.search(lower, hit.start())
                at = lead.start() if lead else hit.start()
                u.cue_word = len(lower[:at].split())
        if not cue and re.match(r"^(?:this is|meet|say hi to) [A-Z]", u.text.strip()):
            cue = 0.8
        prev_speech = next((units[j] for j in range(i - 1, -1, -1) if units[j].kind == "speech"), None)
        pause = u.start - prev_speech.end if prev_speech else 0.0
        cut_near = bool(cuts.size and np.any((cuts >= u.start - max(pause, 0.0) - 0.3) & (cuts <= u.start + 0.4)))
        cues[i] = cue >= 0.8
        scores[i] = (
            0.40 * cue
            + 0.20 * float(depth_pct[i])
            + 0.15 * float(name_shift[i])
            + 0.15 * min(1.0, pause / 2.0)
            + 0.10 * (1.0 if cut_near else 0.0)
        )
    return scores, cues


def segment_stories(
    units: list[Unit], cuts: np.ndarray, profile: Profile, min_story_s: float, max_story_s: float = 360.0
) -> list[list[Unit]]:
    if not units:
        return []
    cue_res = _compile(_CUES, profile.story_cues)
    scores, cues = _boundary_scores(units, cuts, cue_res)
    boundaries: list[int] = []  # unit index where a new story starts

    def pieces_ok(cands: list[int]) -> bool:
        edges = [0, *sorted(cands), len(units)]
        for a, b in zip(edges, edges[1:], strict=False):
            if units[b - 1].end - units[a].start < min_story_s:
                return False
        return True

    ranked = sorted(range(1, len(units)), key=lambda k: scores[k], reverse=True)
    # Pass 1: explicit transitions ("for our next 1v1…") with supporting evidence.
    for i in ranked:
        if cues[i] and scores[i] >= 0.55 and pieces_ok([*boundaries, i]):
            boundaries.append(i)
    for i, is_cue in enumerate(cues):
        units[i].cue = is_cue
    # Long stretches without a spoken transition are split at their best gap (topic + people + pause + cut).
    changed = True
    while changed:
        changed = False
        edges = [0, *sorted(boundaries), len(units)]
        for a, b in zip(edges, edges[1:], strict=False):
            if units[b - 1].end - units[a].start <= max_story_s:
                continue
            inner = sorted(range(a + 1, b), key=lambda k: scores[k], reverse=True)
            for i in inner:
                if scores[i] < 0.25:
                    break
                if pieces_ok([*boundaries, i]):
                    boundaries.append(i)
                    changed = True
                    break
            if changed:
                break
    edges = [0, *sorted(boundaries), len(units)]
    return [units[a:b] for a, b in zip(edges, edges[1:], strict=False)]


# --- labelling ------------------------------------------------------------------------------------


def build_story_model(result: AnalysisResult, profile: Profile, min_story_s: float = 20.0) -> StoryModel:
    ctx = SignalContext.from_analysis(result)
    vocab = _name_vocabulary(result.transcript.sentences)
    units = build_units(result, ctx, profile)
    first_mention: dict[str, int] = {}
    for u in units:
        u.names = _names_in(u.text, vocab)
        for name in u.names:
            first_mention.setdefault(name, u.index)
    mark_ads(units)
    groups = segment_stories(units, np.asarray(result.scene_cuts, dtype=float), profile, min_story_s)
    stories: list[Story] = []
    for gi, group in enumerate(groups):
        counts: Counter[str] = Counter()
        for u in group:
            if not u.teaser:
                counts.update(u.names)
        continued = gi > 0 and not group[0].cue
        stories.append(Story(index=gi, units=group, names=dict(counts), continued=continued))
    return StoryModel(stories=stories, units=units, name_display=vocab, first_mention=first_mention)


def payoff_scores(story: Story) -> list[float]:
    """How much each unit looks like the moment the story pays off.

    A payoff is loud *and confirmed*: the lines right after it name a result ("that was a tie!",
    "he did it", "Noah won"). A spike at the start of a race is not a payoff; its finish is.
    """
    peak = max((u.signal for u in story.units), default=0.0) or 1.0
    out: list[float] = []
    for k, u in enumerate(story.units):
        rel = (u.start - story.start) / max(1.0, story.duration)
        excl = 1.0 if u.text.rstrip().endswith("!") else 0.0
        follow = [v.payoff_words for v in story.units[k + 1 :] if v.start <= u.end + 8.0]
        confirmed = max(follow, default=0.0)
        s = 0.4 * (u.signal / peak) + 0.3 * u.payoff_words + 0.1 * excl + 0.2 * confirmed
        if u.kind == "action":
            s = 0.6 * (u.signal / peak) + 0.3 * confirmed + 0.05
        # Payoffs come after a setup: damp the opening fifth of the story and any line that introduces a segment.
        if rel < 0.2:
            s *= 0.4
        if u.cue:
            s *= 0.3
        out.append(s)
    return out


def pick_payoffs(story: Story, max_payoffs: int = 3, min_sep_s: float = 15.0) -> list[int]:
    """Local maxima of the payoff score, strongest first, at least `min_sep_s` apart.

    The story's final resolution (the last strong payoff) is always included, because that is the
    ending every viewer wants to see.
    """
    scores = payoff_scores(story)
    if not scores:
        return []
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    best = scores[order[0]]
    chosen: list[int] = []
    for i in order:
        if scores[i] < 0.55 * best:
            break
        if all(abs(story.units[i].start - story.units[j].start) >= min_sep_s for j in chosen):
            chosen.append(i)
        if len(chosen) >= max_payoffs:
            break
    # The story's result: the last strong moment that is confirmed by words ("Here is one million dollars!").
    confirmed = [
        i
        for i, u in enumerate(story.units)
        if scores[i] >= 0.45 * best
        and any(v.payoff_words > 0 for v in story.units[i : i + 6] if v.start <= u.end + 8.0)
    ]
    if confirmed:
        final = confirmed[-1]
        chosen = [j for j in chosen if abs(story.units[final].start - story.units[j].start) >= min_sep_s]
        chosen.append(final)
    return chosen
