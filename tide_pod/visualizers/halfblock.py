"""Convert a float32 RGB framebuffer to Rich Strips using half-block characters.

Each terminal cell encodes two vertical pixels via the upper-half-block
character: the foreground color is the top pixel, the background color is
the bottom pixel. This doubles the effective vertical resolution.
"""

from __future__ import annotations

from typing import List

import numpy as np
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip

_HALFBLOCK = "▀"


_EMPTY_STYLE = Style()
_STYLE_CACHE: dict = {}
_CACHE_MAX = 4096


def _get_style(tr: int, tg: int, tb: int, br: int, bg_: int, bb: int) -> Style:
    key = (tr, tg, tb, br, bg_, bb)
    style = _STYLE_CACHE.get(key)
    if style is None:
        style = Style(color=f"rgb({tr},{tg},{tb})", bgcolor=f"rgb({br},{bg_},{bb})")
        if len(_STYLE_CACHE) < _CACHE_MAX:
            _STYLE_CACHE[key] = style
    return style


def render_halfblock_strips(fb: np.ndarray) -> List[Strip]:
    """Render a (H, W, 3) float32 [0..1] framebuffer to terminal strips.

    H must be even. Returns H//2 Strip objects (one per terminal row).
    """
    h, w, _ = fb.shape
    # Quantize to 6-bit (64 levels) then scale back to 0-255 for display.
    # This makes adjacent gradient pixels match more often, dramatically
    # improving RLE compression with no visible quality loss at terminal res.
    quantized = np.clip(fb * 63, 0, 63).astype(np.uint8)
    expanded = (quantized.astype(np.uint16) * 255 // 63).astype(np.uint8)
    strips: List[Strip] = []

    for row in range(0, h, 2):
        top = expanded[row].tolist()
        bot = expanded[row + 1].tolist()
        segments: List[Segment] = []
        col = 0
        while col < w:
            tp = top[col]
            bp = bot[col]
            tr, tg, tb = tp[0], tp[1], tp[2]
            br, bg_, bb = bp[0], bp[1], bp[2]
            run = 1
            while col + run < w:
                ntp = top[col + run]
                nbp = bot[col + run]
                if ntp[0] == tr and ntp[1] == tg and ntp[2] == tb and nbp[0] == br and nbp[1] == bg_ and nbp[2] == bb:
                    run += 1
                else:
                    break
            if tr == 0 and tg == 0 and tb == 0 and br == 0 and bg_ == 0 and bb == 0:
                segments.append(Segment(" " * run, _EMPTY_STYLE))
            else:
                segments.append(Segment(_HALFBLOCK * run, _get_style(tr, tg, tb, br, bg_, bb)))
            col += run
        strips.append(Strip(segments, w))
    return strips
