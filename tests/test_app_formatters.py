"""Tests for the format helpers in tide_pod.app."""

from __future__ import annotations

from tide_pod.app import (
    _QUALITY_LABELS,
    _fmt_alsa_format,
    _fmt_duration,
    _fmt_source,
    _fmt_time_ns,
)
from tide_pod.player import NowPlaying


def test_fmt_time_ns_basic() -> None:
    assert _fmt_time_ns(0) == "0:00"
    assert _fmt_time_ns(60 * 1_000_000_000) == "1:00"
    assert _fmt_time_ns(125 * 1_000_000_000) == "2:05"
    # Negative clamps to 0
    assert _fmt_time_ns(-5) == "0:00"


def test_fmt_duration_handles_zero() -> None:
    assert _fmt_duration(0) == ""
    assert _fmt_duration(None) == ""  # type: ignore[arg-type]


def test_fmt_duration_basic() -> None:
    assert _fmt_duration(45) == "0:45"
    assert _fmt_duration(125) == "2:05"


def test_quality_labels_cover_all_strings() -> None:
    for k in ("LOW", "HIGH", "LOSSLESS", "HI_RES_LOSSLESS"):
        assert k in _QUALITY_LABELS


def test_fmt_alsa_empty() -> None:
    assert _fmt_alsa_format(NowPlaying()) == "—"


def test_fmt_alsa_full() -> None:
    np = NowPlaying(sample_rate=96000, bit_depth=24, channels=2)
    s = _fmt_alsa_format(np)
    assert "24-bit" in s
    assert "96 kHz" in s
    assert "2ch" in s


def test_fmt_source_renders_quality_with_spec() -> None:
    np = NowPlaying(
        source_sample_rate=96000,
        source_bit_depth=24,
        source_quality="HI_RES_LOSSLESS",
    )
    s = _fmt_source(np)
    assert "hi-res lossless" in s.lower()
    assert "24-bit" in s
    assert "96 kHz" in s


def test_fmt_source_unknown_quality_passes_through() -> None:
    np = NowPlaying(source_quality="WEIRD")
    s = _fmt_source(np)
    assert "WEIRD" in s
