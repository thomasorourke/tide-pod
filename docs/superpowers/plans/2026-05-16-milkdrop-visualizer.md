# Milkdrop Terminal Visualizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Milkdrop-inspired full-screen visualizer to tide-pod that renders organic, beat-reactive visuals using Unicode half-block characters with 24-bit true color, driven by the existing FFT and VU data.

**Architecture:** A numpy-based framebuffer (W x H x 3 float32 RGB) renders at ~30fps. Each frame applies a warp transform to the previous frame (zoom/rotate/swirl driven by audio energy), decays it, composites reactive elements (waveforms, radial bursts, particles), and maps the result to half-block characters (the upper-half-block char with independent fg/bg colors giving 2 vertical pixels per cell). A preset system provides swappable configurations that control warp parameters, color palettes, and which overlay shapes are drawn. The visualizer plugs into the existing `Visualizer` base class and `VISUALIZER_OPTIONS` registry.

**Tech Stack:** Python 3.11+, numpy (already a dependency), Textual (already a dependency), Rich Segment/Strip for terminal rendering.

---

## File Structure

| Path | Responsibility |
|------|---------------|
| `tide_pod/visualizers/__init__.py` | Package init, re-exports `MilkdropVisualizer` |
| `tide_pod/visualizers/framebuffer.py` | Core framebuffer: allocate, warp, decay, composite, palette map |
| `tide_pod/visualizers/halfblock.py` | Convert float32 RGB framebuffer to Rich Strips using half-blocks |
| `tide_pod/visualizers/presets.py` | Preset base class + 5 concrete presets |
| `tide_pod/visualizers/widget.py` | Textual `Visualizer` subclass that ties it all together |
| `tests/test_framebuffer.py` | Unit tests for warp, decay, composite math |
| `tests/test_halfblock.py` | Unit tests for RGB-to-half-block rendering |
| `tests/test_presets.py` | Unit tests for preset parameter generation |
| `tide_pod/screens/now_playing.py` | Modify: register the new visualizer in `VISUALIZER_OPTIONS` |

---

### Task 1: Half-Block Renderer

The renderer converts a numpy RGB framebuffer into terminal output. This is the foundation everything else builds on, testable in isolation with no audio dependency.

**Files:**
- Create: `tide_pod/visualizers/__init__.py`
- Create: `tide_pod/visualizers/halfblock.py`
- Test: `tests/test_halfblock.py`

- [ ] **Step 1: Write the failing test for basic half-block conversion**

```python
# tests/test_halfblock.py
"""Tests for the half-block terminal renderer."""

import numpy as np
import pytest

from tide_pod.visualizers.halfblock import render_halfblock_strips


def test_single_row_pair_solid_red():
    """A 1-wide, 2-tall framebuffer: top pixel red, bottom pixel blue."""
    # Framebuffer shape: (height, width, 3), height must be even.
    fb = np.zeros((2, 1, 3), dtype=np.float32)
    fb[0, 0] = [1.0, 0.0, 0.0]  # top pixel: red
    fb[1, 0] = [0.0, 0.0, 1.0]  # bottom pixel: blue
    strips = render_halfblock_strips(fb)
    # 2 pixel rows -> 1 terminal row
    assert len(strips) == 1
    strip = strips[0]
    # The strip should have one segment with the half-block, fg=red, bg=blue
    segments = list(strip)
    assert len(segments) == 1
    seg = segments[0]
    assert seg.text == "▀"
    assert seg.style.color.triplet == (255, 0, 0)
    assert seg.style.bgcolor.triplet == (0, 0, 255)


def test_black_pixels_produce_space():
    """When both top and bottom pixels are black, output a space."""
    fb = np.zeros((2, 3, 3), dtype=np.float32)
    strips = render_halfblock_strips(fb)
    assert len(strips) == 1
    text = "".join(seg.text for seg in strips[0])
    assert text == "   "


def test_width_preserved():
    """Output strip width matches framebuffer width."""
    fb = np.random.default_rng(0).random((4, 20, 3)).astype(np.float32)
    strips = render_halfblock_strips(fb)
    assert len(strips) == 2  # 4 pixel rows -> 2 terminal rows
    for strip in strips:
        total_width = sum(len(seg.text) for seg in strip)
        assert total_width == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source ~/.virtualenvs/tidepod/bin/activate && pytest tests/test_halfblock.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tide_pod.visualizers'`

- [ ] **Step 3: Create the package and implement the half-block renderer**

```python
# tide_pod/visualizers/__init__.py
"""Milkdrop-inspired terminal visualizer."""
```

```python
# tide_pod/visualizers/halfblock.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source ~/.virtualenvs/tidepod/bin/activate && pytest tests/test_halfblock.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tide_pod/visualizers/__init__.py tide_pod/visualizers/halfblock.py tests/test_halfblock.py
git commit -m "feat(viz): add half-block terminal renderer

Converts float32 RGB framebuffers to Rich Strips using the upper-half-block
character with independent fg/bg colors, doubling effective vertical resolution."
```

---

### Task 2: Framebuffer Core (Warp + Decay)

The framebuffer module handles the Milkdrop feedback loop: warp the previous frame (zoom, rotate, swirl) then decay it. This is the core of the organic flowing look.

**Files:**
- Create: `tide_pod/visualizers/framebuffer.py`
- Test: `tests/test_framebuffer.py`

- [ ] **Step 1: Write failing tests for decay and warp**

```python
# tests/test_framebuffer.py
"""Tests for framebuffer warp and decay operations."""

import numpy as np
import pytest

from tide_pod.visualizers.framebuffer import Framebuffer


def test_decay_reduces_brightness():
    """Decay should multiply all pixels by the decay factor."""
    fb = Framebuffer(width=4, height=4)
    fb.buf[:] = 0.8
    fb.decay(factor=0.5)
    assert np.allclose(fb.buf, 0.4, atol=0.01)


def test_decay_clamps_to_zero():
    """Repeated decay should converge to zero, never go negative."""
    fb = Framebuffer(width=4, height=4)
    fb.buf[:] = 1.0
    for _ in range(100):
        fb.decay(factor=0.9)
    assert fb.buf.min() >= 0.0
    assert fb.buf.max() < 0.01


def test_warp_zoom_in_shrinks_content():
    """A zoom > 1 should concentrate content toward the center."""
    fb = Framebuffer(width=10, height=10)
    # Put a white border, black center.
    fb.buf[0, :] = 1.0
    fb.buf[-1, :] = 1.0
    fb.buf[:, 0] = 1.0
    fb.buf[:, -1] = 1.0
    fb.warp(zoom=1.5, rotation=0.0, swirl=0.0)
    # After zoom-in, the center should now have some brightness
    # (border content moved inward).
    center = fb.buf[4:6, 4:6].mean()
    assert center > 0.1


def test_warp_preserves_shape():
    """Warp should not change the framebuffer dimensions."""
    fb = Framebuffer(width=20, height=14)
    fb.buf[:] = np.random.default_rng(1).random((14, 20, 3)).astype(np.float32)
    fb.warp(zoom=1.1, rotation=0.05, swirl=0.02)
    assert fb.buf.shape == (14, 20, 3)


def test_clear_zeros_buffer():
    fb = Framebuffer(width=8, height=6)
    fb.buf[:] = 1.0
    fb.clear()
    assert fb.buf.max() == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source ~/.virtualenvs/tidepod/bin/activate && pytest tests/test_framebuffer.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement Framebuffer class**

```python
# tide_pod/visualizers/framebuffer.py
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
        # Pre-compute coordinate grids for warp (rebuilt on resize).
        self._build_coords()

    def _build_coords(self) -> None:
        # Normalized coords: center is (0,0), range roughly -1..1.
        ys = np.linspace(-1, 1, self.height, dtype=np.float32)
        xs = np.linspace(-1, 1, self.width, dtype=np.float32)
        self._grid_x, self._grid_y = np.meshgrid(xs, ys)
        # Polar coords for swirl.
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
        # Apply swirl: angle offset proportional to radius.
        angle = self._angle + rotation + swirl * self._radius
        # Apply zoom: radius is divided by zoom (zoom>1 means sample closer to center).
        radius = self._radius / max(zoom, 0.01)
        # Convert back to cartesian normalized coords.
        src_x = radius * np.cos(angle)
        src_y = radius * np.sin(angle)
        # Map normalized coords [-1, 1] back to pixel indices.
        src_col = ((src_x + 1) * 0.5 * (self.width - 1)).astype(np.float32)
        src_row = ((src_y + 1) * 0.5 * (self.height - 1)).astype(np.float32)
        # Bilinear interpolation sample from the current buffer.
        self.buf = self._sample_bilinear(src_row, src_col)

    def _sample_bilinear(self, row: np.ndarray, col: np.ndarray) -> np.ndarray:
        """Sample the framebuffer at sub-pixel coordinates with bilinear interp."""
        h, w = self.height, self.width
        # Clamp to valid range.
        row = np.clip(row, 0, h - 1.001)
        col = np.clip(col, 0, w - 1.001)
        r0 = row.astype(np.int32)
        c0 = col.astype(np.int32)
        r1 = np.minimum(r0 + 1, h - 1)
        c1 = np.minimum(c0 + 1, w - 1)
        dr = row - r0
        dc = col - c0
        # Expand fractional parts for broadcasting with RGB.
        dr = dr[:, :, np.newaxis]
        dc = dc[:, :, np.newaxis]
        # Four corners.
        v00 = self.buf[r0, c0]
        v01 = self.buf[r0, c1]
        v10 = self.buf[r1, c0]
        v11 = self.buf[r1, c1]
        # Bilinear blend.
        result = (
            v00 * (1 - dr) * (1 - dc)
            + v01 * (1 - dr) * dc
            + v10 * dr * (1 - dc)
            + v11 * dr * dc
        )
        return result.astype(np.float32)

    def composite_additive(self, layer: np.ndarray) -> None:
        """Add a layer on top of the buffer (additive blend), clamped to 1.0."""
        np.add(self.buf, layer, out=self.buf)
        np.clip(self.buf, 0.0, 1.0, out=self.buf)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source ~/.virtualenvs/tidepod/bin/activate && pytest tests/test_framebuffer.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add tide_pod/visualizers/framebuffer.py tests/test_framebuffer.py
git commit -m "feat(viz): add framebuffer with warp/decay feedback loop

Implements the core Milkdrop trick: warp previous frame (zoom, rotate,
swirl) + decay to create organic flowing trails."
```

---

### Task 3: Preset System

Presets control the visual parameters: how much zoom/rotation/swirl per frame, what color palette to use, and which overlay shapes to draw. Each preset reacts to audio differently.

**Files:**
- Create: `tide_pod/visualizers/presets.py`
- Test: `tests/test_presets.py`

- [ ] **Step 1: Write failing tests for the preset interface**

```python
# tests/test_presets.py
"""Tests for preset parameter generation."""

import numpy as np
import pytest

from tide_pod.visualizers.presets import (
    Preset,
    CosmicBreath,
    NeonTunnel,
    LavaLamp,
    PulseRing,
    StarField,
    PRESETS,
)


@pytest.fixture
def silent_fft():
    return np.zeros(1024, dtype=np.float32)


@pytest.fixture
def loud_fft():
    fft = np.zeros(1024, dtype=np.float32)
    fft[:50] = 0.9  # heavy bass
    fft[50:200] = 0.5  # mids
    fft[200:] = 0.2  # treble
    return fft


def test_all_presets_registered():
    """PRESETS list should contain all five presets."""
    assert len(PRESETS) == 5
    names = [p.name for p in PRESETS]
    assert "Cosmic Breath" in names
    assert "Neon Tunnel" in names
    assert "Lava Lamp" in names
    assert "Pulse Ring" in names
    assert "Star Field" in names


def test_preset_warp_params_in_range(silent_fft):
    """Warp params should be finite and reasonable even with no audio."""
    for preset in PRESETS:
        params = preset.warp_params(silent_fft, bass=0.0, mid=0.0, treble=0.0)
        assert np.isfinite(params["zoom"])
        assert np.isfinite(params["rotation"])
        assert np.isfinite(params["swirl"])
        assert 0.5 < params["zoom"] < 3.0
        assert -1.0 < params["rotation"] < 1.0
        assert -2.0 < params["swirl"] < 2.0
        assert 0.5 < params["decay"] < 1.0


def test_preset_responds_to_bass(loud_fft):
    """With loud bass, warp params should differ from silence."""
    for preset in PRESETS:
        quiet = preset.warp_params(np.zeros(1024, dtype=np.float32), 0.0, 0.0, 0.0)
        loud = preset.warp_params(loud_fft, bass=0.9, mid=0.5, treble=0.2)
        # At least one parameter should change.
        changed = (
            abs(quiet["zoom"] - loud["zoom"]) > 0.001
            or abs(quiet["rotation"] - loud["rotation"]) > 0.001
            or abs(quiet["swirl"] - loud["swirl"]) > 0.001
        )
        assert changed, f"{preset.name} does not respond to audio"


def test_preset_overlay_shape(loud_fft):
    """overlay() should return a valid framebuffer-shaped array or None."""
    for preset in PRESETS:
        layer = preset.overlay(
            width=20, height=10, fft=loud_fft,
            bass=0.9, mid=0.5, treble=0.2, phase=0.0
        )
        if layer is not None:
            assert layer.shape == (10, 20, 3)
            assert layer.dtype == np.float32


def test_preset_palette_returns_rgb():
    """palette() should return a (3,) float32 array."""
    for preset in PRESETS:
        color = preset.palette(phase=0.0, energy=0.5)
        assert color.shape == (3,)
        assert color.dtype == np.float32
        assert (color >= 0.0).all() and (color <= 1.0).all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source ~/.virtualenvs/tidepod/bin/activate && pytest tests/test_presets.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the preset system with 5 presets**

```python
# tide_pod/visualizers/presets.py
"""Milkdrop-style presets: each controls warp, color, and overlay shapes.

A preset is a bundle of parameters that react to audio energy (bass, mid,
treble bands + raw FFT). The feedback loop (warp + decay + overlay) uses
these parameters each frame to produce the organic flowing visuals.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np


class Preset:
    """Base class for visualizer presets."""

    name: str = "Unnamed"

    def warp_params(
        self, fft: np.ndarray, bass: float, mid: float, treble: float
    ) -> Dict[str, float]:
        """Return warp parameters for this frame.

        Returns dict with keys: zoom, rotation, swirl, decay.
        """
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
        """Return an additive overlay layer (H, W, 3) or None."""
        return None

    def palette(self, phase: float, energy: float) -> np.ndarray:
        """Return the dominant color for this frame as (3,) float32 RGB."""
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
        cx, cy = width / 2, height / 2
        ys = np.arange(height, dtype=np.float32)
        xs = np.arange(width, dtype=np.float32)
        gx, gy = np.meshgrid(xs, ys)
        dist = np.sqrt((gx - cx) ** 2 + (gy - cy) ** 2)
        max_r = math.sqrt(cx**2 + cy**2)
        # Expanding ring on beat.
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
        cx, cy = width / 2, height / 2
        ys = np.arange(height, dtype=np.float32)
        xs = np.arange(width, dtype=np.float32)
        gx, gy = np.meshgrid(xs, ys)
        angle = np.arctan2(gy - cy, gx - cx)
        # Radial spokes that rotate with phase.
        n_spokes = 6
        spoke = (np.cos(angle * n_spokes + phase * 4.0) + 1.0) * 0.5
        spoke *= mid * 0.4
        color = self.palette(phase, mid)
        layer[:, :, 0] = spoke * color[0]
        layer[:, :, 1] = spoke * color[1]
        layer[:, :, 2] = spoke * color[2]
        return layer

    def palette(self, phase, energy):
        # Cycle between neon pink and cyan.
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
        # Random-ish blobs seeded by phase (deterministic per-frame).
        rng = np.random.default_rng(int(phase * 10) % 1000)
        n_blobs = 2 + int(bass * 3)
        for _ in range(n_blobs):
            bx = rng.integers(0, width)
            by = rng.integers(0, height)
            ys = np.arange(height, dtype=np.float32)
            xs = np.arange(width, dtype=np.float32)
            gx, gy = np.meshgrid(xs, ys)
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
        cx, cy = width / 2, height / 2
        ys = np.arange(height, dtype=np.float32)
        xs = np.arange(width, dtype=np.float32)
        gx, gy = np.meshgrid(xs, ys)
        dist = np.sqrt((gx - cx) ** 2 + (gy - cy) ** 2)
        max_r = math.sqrt(cx**2 + cy**2)
        # Multiple concentric rings.
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
        # Spawn bright dots near center; the zoom-out warp streaks them outward.
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
        # White-blue sparkle.
        b_boost = 0.3 + 0.2 * math.sin(phase * 5.0)
        return np.array([0.8, 0.85, 0.9 + b_boost * 0.1], dtype=np.float32).clip(0, 1)


PRESETS: List[Preset] = [
    CosmicBreath(),
    NeonTunnel(),
    LavaLamp(),
    PulseRing(),
    StarField(),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source ~/.virtualenvs/tidepod/bin/activate && pytest tests/test_presets.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add tide_pod/visualizers/presets.py tests/test_presets.py
git commit -m "feat(viz): add 5 milkdrop-style presets

Each preset controls warp (zoom/rotation/swirl), decay, color palette,
and overlay shapes, all reactive to bass/mid/treble energy bands."
```

---

### Task 4: Milkdrop Widget (Textual Integration)

The widget ties together the framebuffer, presets, half-block renderer, and existing audio data from `Player`. It subclasses the existing `Visualizer` base class.

**Files:**
- Create: `tide_pod/visualizers/widget.py`
- Modify: `tide_pod/visualizers/__init__.py`
- Modify: `tide_pod/screens/now_playing.py:374-379` (register in `VISUALIZER_OPTIONS`)

- [ ] **Step 1: Implement the Milkdrop widget**

```python
# tide_pod/visualizers/widget.py
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
        # Smoothed audio bands for less jittery motion.
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
        # Height in pixels = terminal rows * 2 (half-block doubles vertical res).
        height = self.size.height * 2
        if width < 2 or height < 2:
            return

        # Ensure framebuffer matches current size.
        if self._fb is None or self._fb.width != width or self._fb.height != height:
            self._fb = Framebuffer(width, height)

        # Extract audio energy bands from FFT data.
        fft = np.array(self._player.spectrum_snapshot(), dtype=np.float32)
        if fft.size > 0:
            n = fft.size
            bass_raw = float(fft[: n // 8].mean()) if n >= 8 else 0.0
            mid_raw = float(fft[n // 8: n // 2].mean()) if n >= 2 else 0.0
            treble_raw = float(fft[n // 2:].mean()) if n >= 2 else 0.0
        else:
            bass_raw = mid_raw = treble_raw = 0.0

        # Smooth the bands (EMA) so visuals don't strobe.
        alpha = 0.4
        self._bass += (bass_raw - self._bass) * alpha
        self._mid += (mid_raw - self._mid) * alpha
        self._treble += (treble_raw - self._treble) * alpha

        # Phase is a continuously increasing value (seconds since start).
        self._phase = time.monotonic() - self._start_time

        # Get warp parameters from the preset.
        params = self._preset.warp_params(fft, self._bass, self._mid, self._treble)

        # Feedback loop: warp then decay.
        self._fb.warp(params["zoom"], params["rotation"], params["swirl"])
        self._fb.decay(params["decay"])

        # Composite overlay from the preset.
        overlay = self._preset.overlay(
            width, height, fft, self._bass, self._mid, self._treble, self._phase
        )
        if overlay is not None:
            self._fb.composite_additive(overlay)

        # Render to half-block strips.
        self._strips = render_halfblock_strips(self._fb.buf)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        if y < len(self._strips):
            return self._strips[y]
        return Strip.blank(self.size.width)
```

- [ ] **Step 2: Update the package init**

```python
# tide_pod/visualizers/__init__.py
"""Milkdrop-inspired terminal visualizer."""

from .widget import MilkdropVisualizer

__all__ = ["MilkdropVisualizer"]
```

- [ ] **Step 3: Register in the visualizer options**

In `tide_pod/screens/now_playing.py`, add the import at the top (after existing imports):
```python
from ..visualizers import MilkdropVisualizer
```

Replace the `VISUALIZER_OPTIONS` list:
```python
VISUALIZER_OPTIONS = [
    ("spectrum", "Spectrum", SpectrumVisualizer),
    ("vu", "VU Meters", VUVisualizer),
    ("milkdrop", "Milkdrop", MilkdropVisualizer),
    ("off", "Off", None),
]
```

- [ ] **Step 4: Run the full test suite**

Run: `source ~/.virtualenvs/tidepod/bin/activate && pytest tests/ -v`
Expected: All existing tests plus new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tide_pod/visualizers/__init__.py tide_pod/visualizers/widget.py tide_pod/screens/now_playing.py
git commit -m "feat(viz): integrate milkdrop visualizer into now-playing screen

Registers as a new option in the visualizer cycle (v key). Runs at 30fps,
pulling FFT data from the player and rendering via half-block characters."
```

---

### Task 5: Preset Cycling Keybinding

Add a key to cycle through Milkdrop presets (separate from the `v` key that cycles between visualizer types). Only active when the Milkdrop visualizer is mounted.

**Files:**
- Modify: `tide_pod/screens/now_playing.py:394-403` (add binding)
- Modify: `tide_pod/screens/now_playing.py:446-456` (add action)

- [ ] **Step 1: Add the preset cycle binding and action**

In `NowPlayingScreen.BINDINGS`, add:
```python
("p", "cycle_preset", "Preset"),
```

Add the action method to `NowPlayingScreen`:
```python
def action_cycle_preset(self) -> None:
    host = self.query_one("#np-vis-host", Container)
    for child in host.children:
        if hasattr(child, "cycle_preset"):
            name = child.cycle_preset()
            self.notify(f"Preset: {name}", timeout=1.5)
            return
    self.notify("Presets only available in Milkdrop mode", timeout=1.5)
```

- [ ] **Step 2: Run the test suite to verify no regressions**

Run: `source ~/.virtualenvs/tidepod/bin/activate && pytest tests/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tide_pod/screens/now_playing.py
git commit -m "feat(viz): add 'p' keybinding to cycle milkdrop presets"
```

---

### Task 6: Manual Visual Smoke Test

No automated test can validate that the visuals look good. This task is a manual verification.

- [ ] **Step 1: Run the app and cycle to the Milkdrop visualizer**

Run: `source ~/.virtualenvs/tidepod/bin/activate && tide-pod`

1. Navigate to Now Playing screen
2. Press `v` until "Milkdrop" appears
3. Play a track
4. Verify: smooth animation, colors react to audio, no flickering/crashes
5. Press `p` to cycle presets, confirm all 5 work
6. Resize terminal, confirm no crash and framebuffer adapts

- [ ] **Step 2: If issues found, fix and re-test; otherwise continue**

- [ ] **Step 3: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix(viz): address visual issues from smoke test"
```
