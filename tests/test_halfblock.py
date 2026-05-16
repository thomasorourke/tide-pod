# tests/test_halfblock.py
"""Tests for the half-block terminal renderer."""

import numpy as np
import pytest

from tide_pod.visualizers.halfblock import render_halfblock_strips


def test_single_row_pair_solid_red():
    """A 1-wide, 2-tall framebuffer: top pixel red, bottom pixel blue."""
    fb = np.zeros((2, 1, 3), dtype=np.float32)
    fb[0, 0] = [1.0, 0.0, 0.0]  # top pixel: red
    fb[1, 0] = [0.0, 0.0, 1.0]  # bottom pixel: blue
    strips = render_halfblock_strips(fb)
    assert len(strips) == 1
    strip = strips[0]
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
    assert len(strips) == 2
    for strip in strips:
        total_width = sum(len(seg.text) for seg in strip)
        assert total_width == 20
