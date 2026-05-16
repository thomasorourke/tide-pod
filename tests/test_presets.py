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
