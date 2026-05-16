"""Textual widget that renders the Milkdrop-style visualizer."""

from __future__ import annotations

import time
from typing import List, TYPE_CHECKING

import numpy as np
from textual.strip import Strip

from ..screens.now_playing import Visualizer
from .framebuffer import Framebuffer
from .halfblock import render_halfblock_strips
from .presets import PRESETS, Preset

if TYPE_CHECKING:
    from ..player import Player


class MilkdropVisualizer(Visualizer):
    """Full-screen Milkdrop-style visualizer using half-block rendering."""

    DISPLAY_NAME = "Milkdrop"
    FPS = 30

    DEFAULT_CSS = """
    MilkdropVisualizer {
        height: 1fr;
        min-height: 6;
        padding: 0;
    }
    """

    def __init__(self, player: "Player") -> None:
        super().__init__(player)
        self._fb: Framebuffer | None = None
        self._strips: List[Strip] = []
        self._preset_index: int = 0
        self._phase: float = 0.0
        self._start_time: float = time.monotonic()
        self._bass: float = 0.0
        self._mid: float = 0.0
        self._treble: float = 0.0

    @property
    def _preset(self) -> Preset:
        return PRESETS[self._preset_index % len(PRESETS)]

    def cycle_preset(self) -> str:
        """Advance to the next preset. Returns the new preset name."""
        self._preset_index = (self._preset_index + 1) % len(PRESETS)
        if self._fb is not None:
            self._fb.clear()
        return self._preset.name

    def _tick(self) -> None:
        width = self.size.width
        height = self.size.height * 2
        if width < 2 or height < 2:
            return

        if self._fb is None or self._fb.width != width or self._fb.height != height:
            self._fb = Framebuffer(width, height)

        fft = np.array(self._player.spectrum_snapshot(), dtype=np.float32)
        if fft.size > 0:
            n = fft.size
            bass_raw = float(fft[: n // 8].mean()) if n >= 8 else 0.0
            mid_raw = float(fft[n // 8: n // 2].mean()) if n >= 2 else 0.0
            treble_raw = float(fft[n // 2:].mean()) if n >= 2 else 0.0
        else:
            bass_raw = mid_raw = treble_raw = 0.0

        alpha = 0.4
        self._bass += (bass_raw - self._bass) * alpha
        self._mid += (mid_raw - self._mid) * alpha
        self._treble += (treble_raw - self._treble) * alpha

        self._phase = time.monotonic() - self._start_time

        params = self._preset.warp_params(fft, self._bass, self._mid, self._treble)

        self._fb.warp(params["zoom"], params["rotation"], params["swirl"])
        self._fb.decay(params["decay"])

        overlay = self._preset.overlay(
            width, height, fft, self._bass, self._mid, self._treble, self._phase
        )
        if overlay is not None:
            self._fb.composite_additive(overlay)

        self._strips = render_halfblock_strips(self._fb.buf)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        if y < len(self._strips):
            return self._strips[y]
        return Strip.blank(self.size.width)
