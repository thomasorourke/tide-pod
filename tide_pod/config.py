"""Config + session paths for tide-pod.

Layout:
    ~/.config/tide-pod/config.toml   user-editable settings
    ~/.config/tide-pod/session.json  Tidal OAuth tokens, managed by tidalapi
    ~/.config/tide-pod/state.json    transient state (last played item)
"""

from __future__ import annotations

import json
import os
import stat
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    d = Path(base) / "tide-pod"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / "config.toml"


def session_path() -> Path:
    return config_dir() / "session.json"


@dataclass
class Config:
    alsa_device: str = ""  # e.g. "hw:3,0"; empty means "not picked yet"
    quality: str = "hi_res_lossless"  # low_96k | low_320k | high_lossless | hi_res_lossless
    # How far back from the appsink's freshest buffer the analyzer reads,
    # in milliseconds. Tunes the visualizer to match what you actually hear.
    # Increase if bars lead the music, decrease if they lag.
    vis_offset_ms: int = 300
    # Visualizer choice on the Now Playing screen: "off", "spectrum", "vu".
    visualizer: str = "spectrum"

    @classmethod
    def load(cls) -> "Config":
        path = config_path()
        if not path.exists():
            return cls()
        with path.open("rb") as f:
            data = tomllib.load(f)
        allowed = {"alsa_device", "quality", "vis_offset_ms", "visualizer"}
        return cls(**{k: v for k, v in data.items() if k in allowed})

    def save(self) -> None:
        path = config_path()
        lines = [f"{k} = {json.dumps(v)}" for k, v in asdict(self).items()]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def secure_session_file() -> None:
    """Tighten permissions on the session file if it exists."""
    path = session_path()
    if path.exists():
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def state_path() -> Path:
    return config_dir() / "state.json"


@dataclass
class LastPlayed:
    kind: str = ""  # "track" | "album" | "playlist" | "mix" | "artist"
    id: str = ""
    name: str = ""
    artist: str = ""
    track_index: int = 0  # within the kind's tracklist

    def is_set(self) -> bool:
        return bool(self.kind and self.id)


@dataclass
class State:
    last_played: LastPlayed = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.last_played is None:
            self.last_played = LastPlayed()

    @classmethod
    def load(cls) -> "State":
        path = state_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        lp = data.get("last_played") or {}
        return cls(
            last_played=LastPlayed(
                kind=str(lp.get("kind") or ""),
                id=str(lp.get("id") or ""),
                name=str(lp.get("name") or ""),
                artist=str(lp.get("artist") or ""),
                track_index=int(lp.get("track_index") or 0),
            )
        )

    def save(self) -> None:
        path = state_path()
        payload = {
            "last_played": {
                "kind": self.last_played.kind,
                "id": self.last_played.id,
                "name": self.last_played.name,
                "artist": self.last_played.artist,
                "track_index": self.last_played.track_index,
            }
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
