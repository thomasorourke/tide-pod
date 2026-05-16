"""Tests for tide_pod.config — XDG paths, config + state round-trip."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from tide_pod import config as cfgmod
from tide_pod.config import Config, LastPlayed, State, secure_session_file


@pytest.fixture
def xdg_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point XDG_CONFIG_HOME at a tmp dir so save/load can run in isolation."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "tide-pod"


def test_config_defaults() -> None:
    c = Config()
    assert c.alsa_device == ""
    assert c.quality == "hi_res_lossless"
    assert c.vis_offset_ms == 300
    assert c.visualizer == "spectrum"


def test_config_round_trip(xdg_home: Path) -> None:
    c = Config(alsa_device="hw:3,0", quality="hi_res_lossless", vis_offset_ms=215, visualizer="vu")
    c.save()
    assert (xdg_home / "config.toml").exists()
    loaded = Config.load()
    assert loaded == c


def test_config_load_ignores_unknown_keys(xdg_home: Path) -> None:
    (xdg_home).mkdir(parents=True, exist_ok=True)
    (xdg_home / "config.toml").write_text(
        'alsa_device = "hw:1,0"\nbogus = "nope"\n', encoding="utf-8"
    )
    loaded = Config.load()
    assert loaded.alsa_device == "hw:1,0"
    # Unknown key must not become an attribute / blow up.
    assert not hasattr(loaded, "bogus")


def test_config_load_missing_returns_defaults(xdg_home: Path) -> None:
    loaded = Config.load()
    assert loaded == Config()


def test_last_played_is_set() -> None:
    assert not LastPlayed().is_set()
    assert not LastPlayed(kind="album").is_set()
    assert not LastPlayed(id="1").is_set()
    assert LastPlayed(kind="album", id="123").is_set()


def test_state_round_trip(xdg_home: Path) -> None:
    s = State(
        last_played=LastPlayed(
            kind="album", id="123", name="Aja", artist="Steely Dan", track_index=2
        )
    )
    s.save()
    loaded = State.load()
    assert loaded.last_played.kind == "album"
    assert loaded.last_played.id == "123"
    assert loaded.last_played.name == "Aja"
    assert loaded.last_played.artist == "Steely Dan"
    assert loaded.last_played.track_index == 2


def test_state_load_missing_returns_defaults(xdg_home: Path) -> None:
    loaded = State.load()
    assert not loaded.last_played.is_set()


def test_state_load_corrupted_returns_defaults(xdg_home: Path) -> None:
    xdg_home.mkdir(parents=True, exist_ok=True)
    (xdg_home / "state.json").write_text("not json {", encoding="utf-8")
    loaded = State.load()
    assert not loaded.last_played.is_set()


def test_secure_session_file_chmods_to_user_only(xdg_home: Path) -> None:
    xdg_home.mkdir(parents=True, exist_ok=True)
    path = cfgmod.session_path()
    path.write_text("dummy")
    # Loosen first
    path.chmod(0o644)
    secure_session_file()
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR
