"""Tests for tide_pod.auth — quality mapping + new_session config wiring."""

from __future__ import annotations

import pytest
from tidalapi.media import Quality

from tide_pod.auth import QUALITY_MAP, new_session
from tide_pod.config import Config


def test_quality_map_covers_all_quality_enum_members() -> None:
    # Every Quality value our config can specify maps to a real tidalapi Quality.
    assert QUALITY_MAP["low_96k"] is Quality.low_96k
    assert QUALITY_MAP["low_320k"] is Quality.low_320k
    assert QUALITY_MAP["high_lossless"] is Quality.high_lossless
    assert QUALITY_MAP["hi_res_lossless"] is Quality.hi_res_lossless


def test_new_session_uses_configured_quality() -> None:
    cfg = Config(quality="high_lossless")
    s = new_session(cfg)
    assert s.config.quality == Quality.high_lossless


def test_new_session_default_is_hi_res() -> None:
    cfg = Config()
    s = new_session(cfg)
    assert s.config.quality == Quality.hi_res_lossless


def test_new_session_falls_back_for_unknown_quality_string() -> None:
    cfg = Config(quality="garbage")
    s = new_session(cfg)
    # Unknown quality string should not crash; falls back to hi_res_lossless.
    assert s.config.quality == Quality.hi_res_lossless
