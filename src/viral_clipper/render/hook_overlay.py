"""The 1-3 second opening hook card, rendered as one transparent PNG."""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw

from viral_clipper.config import CaptionConfig
from viral_clipper.render.captions import _hex_to_rgba, _load_font


def render_hook(text: str, size: tuple[int, int], cfg: CaptionConfig, font_path: Path, dest: Path) -> Path:
    width, height = size
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_size = cfg.hook_font_size
    max_width = int(width * 0.86)
    wrapped: list[str] = []
    font = _load_font(font_path, font_size)
    for _ in range(6):
        font = _load_font(font_path, font_size)
        chars = max(8, int(max_width / (font_size * 0.55)))
        wrapped = textwrap.wrap(text.upper() if cfg.uppercase else text, width=chars) or [text]
        if len(wrapped) <= 3 and all(draw.textlength(w, font=font) <= max_width for w in wrapped):
            break
        font_size = int(font_size * 0.88)

    line_h = int(font_size * 1.25)
    block_h = line_h * len(wrapped)
    y = int(height * cfg.hook_y_ratio - block_h / 2)
    pad = int(font_size * 0.4)
    widest = max(draw.textlength(w, font=font) for w in wrapped)
    box = (
        int((width - widest) / 2 - pad),
        y - pad // 2,
        int((width + widest) / 2 + pad),
        y + block_h + pad // 2,
    )
    draw.rounded_rectangle(box, radius=pad, fill=_hex_to_rgba(cfg.hook_box_color))
    for i, line in enumerate(wrapped):
        lw = draw.textlength(line, font=font)
        draw.text(
            ((width - lw) / 2, y + i * line_h),
            line,
            font=font,
            fill=_hex_to_rgba(cfg.hook_color),
            stroke_width=max(2, cfg.stroke_width // 2),
            stroke_fill=_hex_to_rgba(cfg.stroke_color),
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")
    return dest
