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
    fb.buf[0, :] = 1.0
    fb.buf[-1, :] = 1.0
    fb.buf[:, 0] = 1.0
    fb.buf[:, -1] = 1.0
    fb.warp(zoom=1.5, rotation=0.0, swirl=0.0)
    # Border content should move inward: inner ring (rows/cols 2,7) should
    # now have content that wasn't there before (source had only edge pixels lit)
    inner_ring = fb.buf[2, 3:7].mean()
    assert inner_ring > 0.1


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
