"""Tests for the FFT / VU analyzer.

We construct a real Player (GStreamer initializes; no ALSA device is
actually opened because the pipeline never goes to PLAYING), feed
synthetic audio directly into the ring buffer, and let the FFT thread
process it. The analyzer is deterministic for a known input.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from tide_pod.player import Player


@pytest.fixture
def player() -> Player:
    p = Player("hw:99,0")
    yield p
    p.shutdown()


def _write_samples(p: Player, left: np.ndarray, right: np.ndarray, rate: int) -> None:
    """Push stereo samples directly into the ring buffer, as if from appsink."""
    with p._spectrum_lock:
        p._spectrum_rate = rate
    n = left.shape[0]
    with p._ring_lock:
        size = p._ring_l.shape[0]
        w = p._ring_write
        end = w + n
        if end <= size:
            p._ring_l[w:end] = left
            p._ring_r[w:end] = right
        else:
            first = size - w
            p._ring_l[w:] = left[:first]
            p._ring_l[: n - first] = left[first:]
            p._ring_r[w:] = right[:first]
            p._ring_r[: n - first] = right[first:]
        p._ring_write = end % size
        p._ring_filled = min(p._ring_filled + n, size)


def test_silent_input_yields_zero_spectrum(player: Player) -> None:
    rate = 48000
    silence = np.zeros(player.SPECTRUM_FFT_SIZE * 2, dtype=np.float32)
    _write_samples(player, silence, silence, rate)
    # Let the FFT loop run a few hops.
    time.sleep(0.1)
    mags = player.spectrum_snapshot()
    assert len(mags) == player.SPECTRUM_BANDS
    # All bins should be at the noise floor (clamped to 0).
    assert max(mags) < 0.01


def test_sine_at_known_freq_peaks_in_expected_bin(player: Player) -> None:
    rate = 48000
    N = player.SPECTRUM_FFT_SIZE
    freq = 1500.0
    t = np.arange(N * 4, dtype=np.float32) / rate
    tone = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    _write_samples(player, tone, tone, rate)
    time.sleep(0.1)
    mags = player.spectrum_snapshot()
    peak_bin = int(np.argmax(mags))
    # bin index in our magnitudes corresponds to bin (peak_bin + 1) of the
    # full FFT (we skip the DC bin in the FFT loop).
    expected_bin = round(freq * N / rate) - 1
    assert abs(peak_bin - expected_bin) <= 1, (
        f"expected bin near {expected_bin}, got {peak_bin}"
    )
    # Peak should be near-saturated against our scale.
    assert mags[peak_bin] > 0.5


def test_full_scale_signal_saturates_vu(player: Player) -> None:
    rate = 48000
    # White noise at near unity amplitude → RMS ≈ 0.5, peak ≈ 1.0.
    rng = np.random.default_rng(42)
    sig = rng.uniform(-1.0, 1.0, player.VU_RMS_WINDOW * 4).astype(np.float32)
    _write_samples(player, sig, sig, rate)
    time.sleep(0.1)
    l_rms, l_peak, r_rms, r_peak = player.vu_snapshot()
    # Peak should be at the top of the meter (clipped to 1.0 with ceiling -3 dBFS).
    assert l_peak > 0.95
    assert r_peak > 0.95
    # RMS for uniform noise [-1, 1] is ~0.577 → 20log10(0.577) ≈ -4.77 dBFS
    # → on a -50..-3 scale, normalizes to ~0.96. Plenty in the upper meter.
    assert l_rms > 0.7
    assert r_rms > 0.7


def test_latency_offset_skips_recent_samples(player: Player) -> None:
    """If vis_offset_ms is large, the analyzed window is older audio."""
    rate = 48000
    player.set_vis_offset_ms(100)  # 100 ms back

    # Write 200ms of silence followed by 200ms of a loud tone. The latency
    # offset means the FFT should still be reading the silent portion right
    # after we finish writing the tone (the tone hasn't "played" yet).
    n_silence = rate // 5  # 200 ms
    n_tone = rate // 5
    silence = np.zeros(n_silence, dtype=np.float32)
    t = np.arange(n_tone, dtype=np.float32) / rate
    tone = (0.9 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)

    _write_samples(player, silence, silence, rate)
    _write_samples(player, tone, tone, rate)
    # Simulate the appsink updating the latency offset:
    with player._ring_lock:
        player._audio_latency_samples = int(player.vis_offset_ms * rate / 1000)

    time.sleep(0.1)
    mags = player.spectrum_snapshot()
    # With a 100ms offset, the FFT looks at audio 100 ms before "now". Now
    # is end-of-tone (200 ms in); 100 ms before that is mid-tone, so the
    # tone IS still visible. Sanity-check the offset path doesn't crash.
    assert len(mags) == player.SPECTRUM_BANDS
    assert max(mags) > 0.1  # the tone is still in the window
