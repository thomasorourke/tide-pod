"""ALSA device enumeration.

Parses `aplay -l` (concise, hw: addressable). Each entry maps to a
`hw:CARD,DEV` device string usable directly with `alsasink device=...`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class AlsaDevice:
    card: int
    device: int
    card_name: str
    device_name: str

    @property
    def address(self) -> str:
        return f"hw:{self.card},{self.device}"

    @property
    def label(self) -> str:
        return f"{self.address}  —  {self.card_name} / {self.device_name}"


@dataclass
class BackendChoice:
    """What the device picker hands back: a backend, plus device when applicable.

    "alsa" + AlsaDevice: bit-perfect exclusive output on hw:CARD,DEV.
    "pulse" (no device): PulseAudio/PipeWire default sink, shared with other apps.
    """

    backend: str  # "alsa" | "pulse"
    alsa: Optional[AlsaDevice] = None


_LINE_RE = re.compile(
    r"^card\s+(\d+):\s+([^\[]+)\[([^\]]+)\],\s+device\s+(\d+):\s+([^\[]+)\[([^\]]+)\]"
)


def parse_aplay_output(text: str) -> List[AlsaDevice]:
    """Parse the textual output of `aplay -l` into AlsaDevice records."""
    devices: List[AlsaDevice] = []
    for line in text.splitlines():
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        card_idx, _card_short, card_name, dev_idx, _dev_short, dev_name = m.groups()
        devices.append(
            AlsaDevice(
                card=int(card_idx),
                device=int(dev_idx),
                card_name=card_name.strip(),
                device_name=dev_name.strip(),
            )
        )
    return devices


def list_devices() -> List[AlsaDevice]:
    """Return playback devices reported by `aplay -l`.

    Returns an empty list if aplay is missing or returns nothing usable.
    """
    if not shutil.which("aplay"):
        return []
    try:
        out = subprocess.run(
            ["aplay", "-l"], capture_output=True, text=True, timeout=5, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_aplay_output(out)


def resolve(card_name: str, device_index: int = 0) -> Optional[AlsaDevice]:
    """Find the current AlsaDevice matching a saved card name + device.

    Card numbering shifts when USB devices are plugged in different orders,
    so we pin by the human-readable card name (which is stable per-device)
    and look up the current hw:CARD,DEV at startup.
    """
    if not card_name:
        return None
    for d in list_devices():
        if d.card_name == card_name and d.device == device_index:
            return d
    return None
