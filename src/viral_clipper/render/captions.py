"""Word-by-word captions rendered with Pillow as a transparent PNG sequence.

Why PNGs and not libass: many FFmpeg builds (including Homebrew's) ship without libass, and
Pillow gives exact control of the bold "active word highlighted" look. The sequence is fed to
FFmpeg through the concat demuxer as one overlay stream.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from viral_clipper.config import CaptionConfig
from viral_clipper.models import Word

log = logging.getLogger(__name__)

LINE_GAP_S = 0.8  # a pause longer than this starts a new caption line
MIN_STATE_S = 0.08


@dataclass(frozen=True)
class CaptionLine:
    words: list[Word]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass(frozen=True)
class OverlayItem:
    path: Path
    duration: float


def clip_timeline_words(
    words_by_part: list[list[Word]], parts: list[tuple[float, float]], durations: list[float]
) -> tuple[list[Word], set[int]]:
    """Map source-time words onto the clip's timeline (after jump cuts).

    Returns the words in clip seconds and the indices of words that open a new segment, so a caption
    line never spans a cut. Whisper splits "$100,000" into "$100" + ",000": those pieces are re-joined.
    """
    out: list[Word] = []
    breaks: set[int] = set()
    offset = 0.0
    for (a, _b), dur, words in zip(parts, durations, words_by_part, strict=True):
        first = True
        for w in words:
            mid = (w.start + w.end) / 2
            if not (a <= mid <= a + dur):
                continue
            start = max(0.0, w.start - a) + offset
            end = min(dur, w.end - a) + offset
            text = w.text.strip()
            if out and not first and text[:1] in {",", "-", "'", "%"} and len(text) > 1:
                prev = out[-1]
                out[-1] = Word(text=prev.text + text, start=prev.start, end=end, prob=prev.prob)
                continue
            if first:
                breaks.add(len(out))
                first = False
            out.append(Word(text=text, start=start, end=max(end, start + 0.05), prob=w.prob))
        offset += dur
    return out, breaks


def group_lines(words: list[Word], words_per_line: int, breaks: set[int] | None = None) -> list[CaptionLine]:
    lines: list[CaptionLine] = []
    current: list[Word] = []
    for i, w in enumerate(words):
        cut_here = breaks is not None and i in breaks
        if current and (len(current) >= words_per_line or w.start - current[-1].end > LINE_GAP_S or cut_here):
            lines.append(CaptionLine(current))
            current = []
        current.append(w)
        if w.text.rstrip("\"'”)").endswith((".", "!", "?")) and len(current) >= 2:
            lines.append(CaptionLine(current))
            current = []
    if current:
        lines.append(CaptionLine(current))
    return lines


def _hex_to_rgba(value: str) -> tuple[int, int, int, int]:
    v = value.lstrip("#")
    if len(v) == 6:
        v += "FF"
    return tuple(int(v[i : i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]


def _load_font(font_path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(font_path), size)
    except OSError:
        log.warning("font %s not found; falling back to Pillow default", font_path)
        return ImageFont.load_default(size)  # type: ignore[return-value]


def _fit_font(font_path: Path, size: int, text: str, max_width: int, stroke: int) -> ImageFont.FreeTypeFont:
    font = _load_font(font_path, size)
    while size > 28:
        bbox = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=font, stroke_width=stroke)
        if bbox[2] - bbox[0] <= max_width:
            break
        size = int(size * 0.92)
        font = _load_font(font_path, size)
    return font


def render_line_state(
    line: CaptionLine,
    active: int,
    size: tuple[int, int],
    cfg: CaptionConfig,
    font_path: Path,
    dest: Path,
) -> Path:
    """One PNG: the whole line, with word `active` in the highlight colour and slightly larger."""
    width, height = size
    texts = [w.text.upper() if cfg.uppercase else w.text for w in line.words]
    full = " ".join(texts)
    font = _fit_font(font_path, cfg.font_size, full, int(width * 0.88), cfg.stroke_width)
    big = _load_font(font_path, int(font.size * 1.08))
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    space = draw.textlength(" ", font=font)
    widths = [draw.textlength(t, font=(big if i == active else font)) for i, t in enumerate(texts)]
    total = sum(widths) + space * (len(texts) - 1)
    x = (width - total) / 2
    y_centre = height * cfg.y_ratio
    for i, t in enumerate(texts):
        f = big if i == active else font
        colour = _hex_to_rgba(cfg.highlight_color if i == active else cfg.text_color)
        bbox = draw.textbbox((0, 0), t, font=f, stroke_width=cfg.stroke_width)
        y = y_centre - (bbox[3] - bbox[1]) / 2 - bbox[1]
        draw.text(
            (x, y),
            t,
            font=f,
            fill=colour,
            stroke_width=cfg.stroke_width,
            stroke_fill=_hex_to_rgba(cfg.stroke_color),
        )
        x += widths[i] + space
    img.save(dest, "PNG", optimize=False, compress_level=3)
    return dest


def blank_png(size: tuple[int, int], dest: Path) -> Path:
    if not dest.exists():
        Image.new("RGBA", size, (0, 0, 0, 0)).save(dest, "PNG")
    return dest


def build_caption_sequence(
    words: list[Word],
    clip_start: float,
    clip_duration: float,
    size: tuple[int, int],
    cfg: CaptionConfig,
    font_path: Path,
    out_dir: Path,
    breaks: set[int] | None = None,
) -> tuple[list[OverlayItem], list[CaptionLine]]:
    """Render every word-state and return a gapless timeline covering the whole clip."""
    out_dir.mkdir(parents=True, exist_ok=True)
    blank = blank_png(size, out_dir / "blank.png")
    lines = group_lines(words, cfg.words_per_line, breaks)
    items: list[OverlayItem] = []
    cursor = 0.0
    n = 0
    for li, line in enumerate(lines):
        line_start = max(0.0, line.start - clip_start)
        if line_start > cursor + MIN_STATE_S:
            items.append(OverlayItem(blank, line_start - cursor))
            cursor = line_start
        next_line_start = (lines[li + 1].start - clip_start) if li + 1 < len(lines) else clip_duration
        for wi, w in enumerate(line.words):
            state_start = max(cursor, w.start - clip_start)
            if wi + 1 < len(line.words):
                state_end = line.words[wi + 1].start - clip_start
            else:
                # Hold the finished line briefly, but never into the next line.
                state_end = min(next_line_start, w.end - clip_start + 0.25, clip_duration)
            if state_end - state_start < MIN_STATE_S:
                continue
            n += 1
            png = render_line_state(line, wi, size, cfg, font_path, out_dir / f"c{n:04d}.png")
            items.append(OverlayItem(png, state_end - state_start))
            cursor = state_end
    if cursor < clip_duration:
        items.append(OverlayItem(blank, clip_duration - cursor))
    return items, lines


def write_concat_list(items: list[OverlayItem], dest: Path) -> Path:
    """FFmpeg concat demuxer list. The last file is repeated without a duration as the docs require."""
    lines = ["ffconcat version 1.0"]
    for item in items:
        lines.append(f"file '{_concat_escape(item.path)}'")
        lines.append(f"duration {max(MIN_STATE_S, item.duration):.3f}")
    if items:
        lines.append(f"file '{_concat_escape(items[-1].path)}'")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def _concat_escape(path: Path) -> str:
    return str(path.resolve()).replace("'", r"'\''")


def write_subtitle_files(lines: list[CaptionLine], clip_start: float, srt_path: Path, ass_path: Path) -> None:
    """Plain .srt and .ass for anyone who wants to restyle captions in an editor."""
    import pysubs2

    subs = pysubs2.SSAFile()
    for line in lines:
        subs.append(
            pysubs2.SSAEvent(
                start=int(max(0.0, line.start - clip_start) * 1000),
                end=int(max(0.0, line.end - clip_start) * 1000) + 200,
                text=line.text,
            )
        )
    subs.save(str(srt_path), format_="srt")
    subs.save(str(ass_path), format_="ass")
