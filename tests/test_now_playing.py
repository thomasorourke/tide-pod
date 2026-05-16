"""Tests for now_playing helpers: visualizer registry, log resampling."""

from __future__ import annotations

import numpy as np
import pytest

from tide_pod.screens.now_playing import (
    SpectrumVisualizer,
    VISUALIZER_OPTIONS,
    VUVisualizer,
    visualizer_index_for,
)


def test_visualizer_index_known_keys() -> None:
    assert visualizer_index_for("spectrum") == 0
    assert visualizer_index_for("vu") == 1
    assert visualizer_index_for("milkdrop") == 2
    assert visualizer_index_for("art") == 3
    assert visualizer_index_for("off") == 4


def test_visualizer_index_unknown_falls_back_to_zero() -> None:
    assert visualizer_index_for("nope") == 0
    assert visualizer_index_for("") == 0


def test_visualizer_options_have_required_shape() -> None:
    # (config-key, display-name, widget-class-or-None)
    for entry in VISUALIZER_OPTIONS:
        key, name, cls = entry
        assert isinstance(key, str) and key
        assert isinstance(name, str) and name
        # cls is either a Visualizer subclass or None ("off").
        assert cls is None or hasattr(cls, "DISPLAY_NAME")


def test_log_resample_indices_are_contiguous_and_monotonic() -> None:
    """np.maximum.reduceat needs the indices to be increasing without gaps."""
    sv = SpectrumVisualizer.__new__(SpectrumVisualizer)
    # Initialize the index arrays the way the constructor does.
    sv._idx_lo = np.zeros(1, dtype=np.int32)
    sv._idx_hi = np.zeros(1, dtype=np.int32)
    sv._rebuild_indices(bands=512, cols=80)
    assert sv._idx_lo.shape == (80,)
    assert sv._idx_hi.shape == (80,)
    # First range starts at index 1 (DC bin skipped).
    assert sv._idx_lo[0] == 1
    # Each column's hi must equal the next column's lo (contiguous).
    for i in range(80 - 1):
        assert sv._idx_hi[i] == sv._idx_lo[i + 1]
    # Increasing.
    assert all(sv._idx_lo[i + 1] > sv._idx_lo[i] for i in range(79))
    # Last hi is exactly the band count.
    assert sv._idx_hi[-1] == 512


def test_log_resample_low_band_energy_spreads_across_many_columns() -> None:
    """Log spacing should give the low bins more columns than linear."""
    sv = SpectrumVisualizer.__new__(SpectrumVisualizer)
    sv._idx_lo = np.zeros(1, dtype=np.int32)
    sv._idx_hi = np.zeros(1, dtype=np.int32)
    sv._rebuild_indices(bands=256, cols=64)
    # In a log layout, the first half of the columns should map to the lowest
    # quarter of the bands. (With purely linear, half the cols → half the bands.)
    midpoint_band = sv._idx_hi[31]  # band index covered by column 32
    assert midpoint_band < 128, f"midpoint band was {midpoint_band}, too linear"
