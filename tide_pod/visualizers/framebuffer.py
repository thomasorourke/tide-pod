"""Core framebuffer with warp and decay for the feedback loop.

The Milkdrop effect comes from repeatedly warping the previous frame
(zoom/rotate/swirl) and fading it, then compositing new reactive
elements on top. The trails and organic motion emerge from this loop.
"""

from __future__ import annotations

import numpy as np


class Framebuffer:
    """A W x H RGB float32 framebuffer with warp and decay operations."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.buf = np.zeros((height, width, 3), dtype=np.float32)
        self._build_coords()

    def _build_coords(self) -> None:
        ys = np.linspace(-1, 1, self.height, dtype=np.float32)
        xs = np.linspace(-1, 1, self.width, dtype=np.float32)
        self._grid_x, self._grid_y = np.meshgrid(xs, ys)
        self._radius = np.sqrt(self._grid_x**2 + self._grid_y**2)
        self._angle = np.arctan2(self._grid_y, self._grid_x)

    def resize(self, width: int, height: int) -> None:
        if width == self.width and height == self.height:
            return
        self.width = width
        self.height = height
        self.buf = np.zeros((height, width, 3), dtype=np.float32)
        self._build_coords()

    def clear(self) -> None:
        self.buf[:] = 0.0

    def decay(self, factor: float) -> None:
        self.buf *= factor

    def warp(self, zoom: float, rotation: float, swirl: float) -> None:
        """Remap the framebuffer: zoom toward center, rotate, and swirl.

        zoom: >1 zooms in (content moves toward center), <1 zooms out.
        rotation: radians, global rotation around center.
        swirl: radians per unit radius, adds rotation that increases with distance.
        """
        angle = self._angle + rotation + swirl * self._radius
        radius = self._radius * zoom
        src_x = radius * np.cos(angle)
        src_y = radius * np.sin(angle)
        src_col = ((src_x + 1) * 0.5 * (self.width - 1)).astype(np.float32)
        src_row = ((src_y + 1) * 0.5 * (self.height - 1)).astype(np.float32)
        self.buf = self._sample_bilinear(src_row, src_col)

    def _sample_bilinear(self, row: np.ndarray, col: np.ndarray) -> np.ndarray:
        """Sample the framebuffer at sub-pixel coordinates with bilinear interp."""
        h, w = self.height, self.width
        row = np.clip(row, 0, h - 1.001)
        col = np.clip(col, 0, w - 1.001)
        r0 = row.astype(np.int32)
        c0 = col.astype(np.int32)
        r1 = np.minimum(r0 + 1, h - 1)
        c1 = np.minimum(c0 + 1, w - 1)
        dr = row - r0
        dc = col - c0
        dr = dr[:, :, np.newaxis]
        dc = dc[:, :, np.newaxis]
        v00 = self.buf[r0, c0]
        v01 = self.buf[r0, c1]
        v10 = self.buf[r1, c0]
        v11 = self.buf[r1, c1]
        return (
            v00 * (1 - dr) * (1 - dc)
            + v01 * (1 - dr) * dc
            + v10 * dr * (1 - dc)
            + v11 * dr * dc
        )

    def composite_additive(self, layer: np.ndarray) -> None:
        """Add a layer on top of the buffer (additive blend), clamped to 1.0."""
        np.add(self.buf, layer, out=self.buf)
        np.clip(self.buf, 0.0, 1.0, out=self.buf)
