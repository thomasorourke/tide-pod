"""Milkdrop-style presets: each controls warp, color, and overlay shapes.

A preset is a bundle of parameters that react to audio energy (bass, mid,
treble bands + raw FFT). The feedback loop (warp + decay + overlay) uses
these parameters each frame to produce the organic flowing visuals.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np

_grid_cache: dict = {}


def _pixel_grid(width: int, height: int):
    """Return cached (gx, gy, dist, angle) arrays for the given dimensions."""
    key = (width, height)
    cached = _grid_cache.get(key)
    if cached is not None:
        return cached
    ys = np.arange(height, dtype=np.float32)
    xs = np.arange(width, dtype=np.float32)
    gx, gy = np.meshgrid(xs, ys)
    cx, cy = width / 2.0, height / 2.0
    dx, dy = gx - cx, gy - cy
    dist = np.sqrt(dx**2 + dy**2)
    angle = np.arctan2(dy, dx)
    result = (gx, gy, dist, angle)
    _grid_cache[key] = result
    return result


class Preset:
    """Base class for visualizer presets."""

    name: str = "Unnamed"

    def warp_params(
        self, fft: np.ndarray, bass: float, mid: float, treble: float
    ) -> Dict[str, float]:
        return {"zoom": 1.01, "rotation": 0.0, "swirl": 0.0, "decay": 0.95}

    def overlay(
        self,
        width: int,
        height: int,
        fft: np.ndarray,
        bass: float,
        mid: float,
        treble: float,
        phase: float,
    ) -> Optional[np.ndarray]:
        return None

    def palette(self, phase: float, energy: float) -> np.ndarray:
        return np.array([1.0, 1.0, 1.0], dtype=np.float32)


class CosmicBreath(Preset):
    """Slow breathing zoom with gentle rotation. Deep space palette."""

    name = "Cosmic Breath"

    def warp_params(self, fft, bass, mid, treble):
        zoom = 1.02 + bass * 0.04
        rotation = 0.01 + mid * 0.02
        swirl = 0.005 + treble * 0.01
        decay = 0.96 - bass * 0.03
        return {"zoom": zoom, "rotation": rotation, "swirl": swirl, "decay": decay}

    def overlay(self, width, height, fft, bass, mid, treble, phase):
        if bass < 0.2:
            return None
        layer = np.zeros((height, width, 3), dtype=np.float32)
        _gx, _gy, dist, _angle = _pixel_grid(width, height)
        max_r = math.sqrt((width / 2) ** 2 + (height / 2) ** 2)
        ring_r = (phase % 1.0) * max_r
        ring_width = 1.5 + bass * 2.0
        ring = np.exp(-((dist - ring_r) ** 2) / (2 * ring_width**2))
        color = self.palette(phase, bass)
        layer[:, :, 0] = ring * color[0] * bass
        layer[:, :, 1] = ring * color[1] * bass
        layer[:, :, 2] = ring * color[2] * bass
        return layer

    def palette(self, phase, energy):
        r = 0.3 + 0.3 * math.sin(phase * 2.0)
        g = 0.1 + 0.2 * math.sin(phase * 2.0 + 2.1)
        b = 0.6 + 0.4 * math.sin(phase * 2.0 + 4.2)
        return np.array([r, g, b], dtype=np.float32)


class NeonTunnel(Preset):
    """Fast zoom-in creating a tunnel effect. Neon pink/cyan."""

    name = "Neon Tunnel"

    def warp_params(self, fft, bass, mid, treble):
        zoom = 1.06 + bass * 0.08
        rotation = 0.03 + treble * 0.05
        swirl = 0.0
        decay = 0.92 - bass * 0.04
        return {"zoom": zoom, "rotation": rotation, "swirl": swirl, "decay": decay}

    def overlay(self, width, height, fft, bass, mid, treble, phase):
        layer = np.zeros((height, width, 3), dtype=np.float32)
        _gx, _gy, _dist, angle = _pixel_grid(width, height)
        n_spokes = 6
        spoke = (np.cos(angle * n_spokes + phase * 4.0) + 1.0) * 0.5
        spoke *= mid * 0.4
        color = self.palette(phase, mid)
        layer[:, :, 0] = spoke * color[0]
        layer[:, :, 1] = spoke * color[1]
        layer[:, :, 2] = spoke * color[2]
        return layer

    def palette(self, phase, energy):
        t = (math.sin(phase * 3.0) + 1.0) * 0.5
        pink = np.array([1.0, 0.2, 0.8], dtype=np.float32)
        cyan = np.array([0.1, 0.9, 1.0], dtype=np.float32)
        return (pink * (1 - t) + cyan * t).astype(np.float32)


class LavaLamp(Preset):
    """Slow swirl with warm colors. Minimal zoom, heavy swirl."""

    name = "Lava Lamp"

    def warp_params(self, fft, bass, mid, treble):
        zoom = 1.005 + bass * 0.01
        rotation = 0.0
        swirl = 0.08 + mid * 0.1
        decay = 0.97 - bass * 0.02
        return {"zoom": zoom, "rotation": rotation, "swirl": swirl, "decay": decay}

    def overlay(self, width, height, fft, bass, mid, treble, phase):
        if bass < 0.15:
            return None
        layer = np.zeros((height, width, 3), dtype=np.float32)
        rng = np.random.default_rng(int(phase * 10) % 1000)
        n_blobs = 2 + int(bass * 3)
        gx, gy, _dist, _angle = _pixel_grid(width, height)
        for _ in range(n_blobs):
            bx = rng.integers(0, width)
            by = rng.integers(0, height)
            dist = np.sqrt((gx - bx) ** 2 + (gy - by) ** 2)
            blob = np.exp(-(dist**2) / (2.0 * (1.5 + bass) ** 2))
            color = self.palette(phase + rng.random(), bass)
            layer[:, :, 0] += blob * color[0] * 0.3
            layer[:, :, 1] += blob * color[1] * 0.3
            layer[:, :, 2] += blob * color[2] * 0.3
        np.clip(layer, 0.0, 1.0, out=layer)
        return layer

    def palette(self, phase, energy):
        r = 0.8 + 0.2 * math.sin(phase * 1.5)
        g = 0.3 + 0.3 * math.sin(phase * 1.5 + 1.0)
        b = 0.05 + 0.1 * math.sin(phase * 1.5 + 3.0)
        return np.array([r, g, b], dtype=np.float32)


class PulseRing(Preset):
    """Concentric rings that pulse outward on beats. Clean and geometric."""

    name = "Pulse Ring"

    def warp_params(self, fft, bass, mid, treble):
        zoom = 1.03 + bass * 0.05
        rotation = treble * 0.03
        swirl = 0.0
        decay = 0.93 - bass * 0.03
        return {"zoom": zoom, "rotation": rotation, "swirl": swirl, "decay": decay}

    def overlay(self, width, height, fft, bass, mid, treble, phase):
        layer = np.zeros((height, width, 3), dtype=np.float32)
        _gx, _gy, dist, _angle = _pixel_grid(width, height)
        max_r = math.sqrt((width / 2) ** 2 + (height / 2) ** 2)
        n_rings = 3
        for i in range(n_rings):
            ring_phase = (phase + i / n_rings) % 1.0
            ring_r = ring_phase * max_r
            ring_w = 0.8 + bass
            ring = np.exp(-((dist - ring_r) ** 2) / (2 * ring_w**2))
            color = self.palette(phase + i * 0.33, bass)
            intensity = 0.5 + bass * 0.5
            layer[:, :, 0] += ring * color[0] * intensity
            layer[:, :, 1] += ring * color[1] * intensity
            layer[:, :, 2] += ring * color[2] * intensity
        np.clip(layer, 0.0, 1.0, out=layer)
        return layer

    def palette(self, phase, energy):
        r = 0.5 + 0.5 * math.sin(phase * 4.0)
        g = 0.5 + 0.5 * math.sin(phase * 4.0 + 2.1)
        b = 0.5 + 0.5 * math.sin(phase * 4.0 + 4.2)
        return np.array([r, g, b], dtype=np.float32)


class StarField(Preset):
    """Zoom-out creating a flying-through-stars effect. White/blue sparks."""

    name = "Star Field"

    def warp_params(self, fft, bass, mid, treble):
        zoom = 0.97 - bass * 0.03  # zoom OUT (content expands from center)
        rotation = 0.005 + treble * 0.01
        swirl = 0.0
        decay = 0.90 - bass * 0.05
        return {"zoom": zoom, "rotation": rotation, "swirl": swirl, "decay": decay}

    def overlay(self, width, height, fft, bass, mid, treble, phase):
        layer = np.zeros((height, width, 3), dtype=np.float32)
        rng = np.random.default_rng(int(phase * 30) % 10000)
        n_stars = 3 + int(bass * 8)
        cx, cy = width // 2, height // 2
        spread = 2 + int(mid * 3)
        for _ in range(n_stars):
            sx = cx + rng.integers(-spread, spread + 1)
            sy = cy + rng.integers(-spread, spread + 1)
            if 0 <= sx < width and 0 <= sy < height:
                color = self.palette(phase + rng.random(), bass)
                brightness = 0.6 + bass * 0.4
                layer[sy, sx] = color * brightness
        return layer

    def palette(self, phase, energy):
        b_boost = 0.3 + 0.2 * math.sin(phase * 5.0)
        return np.array([0.8, 0.85, 0.9 + b_boost * 0.1], dtype=np.float32).clip(0, 1)


PRESETS: List[Preset] = [
    CosmicBreath(),
    NeonTunnel(),
    LavaLamp(),
    PulseRing(),
    StarField(),
]
