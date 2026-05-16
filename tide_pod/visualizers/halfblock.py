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


def render_halfblock_strips(fb: np.ndarray) -> List[Strip]:
    """Render a (H, W, 3) float32 [0..1] framebuffer to terminal strips.

    H must be even. Returns H//2 Strip objects (one per terminal row).
    """
    h, w, _ = fb.shape
    clipped = np.clip(fb * 255, 0, 255).astype(np.uint8)
    strips: List[Strip] = []

    for row in range(0, h, 2):
        top = clipped[row]      # shape (W, 3)
        bot = clipped[row + 1]  # shape (W, 3)
        segments: List[Segment] = []
        col = 0
        while col < w:
            tr, tg, tb = int(top[col, 0]), int(top[col, 1]), int(top[col, 2])
            br, bg_, bb = int(bot[col, 0]), int(bot[col, 1]), int(bot[col, 2])
            # Run-length: merge consecutive cells with the same color pair.
            run = 1
            while col + run < w:
                ntr, ntg, ntb = int(top[col + run, 0]), int(top[col + run, 1]), int(top[col + run, 2])
                nbr, nbg, nbb = int(bot[col + run, 0]), int(bot[col + run, 1]), int(bot[col + run, 2])
                if (ntr, ntg, ntb) == (tr, tg, tb) and (nbr, nbg, nbb) == (br, bg_, bb):
                    run += 1
                else:
                    break
            top_black = (tr == 0 and tg == 0 and tb == 0)
            bot_black = (br == 0 and bg_ == 0 and bb == 0)
            if top_black and bot_black:
                segments.append(Segment(" " * run, Style()))
            else:
                style = Style(
                    color=f"rgb({tr},{tg},{tb})",
                    bgcolor=f"rgb({br},{bg_},{bb})",
                )
                segments.append(Segment(_HALFBLOCK * run, style))
            col += run
        strips.append(Strip(segments, w))
    return strips
