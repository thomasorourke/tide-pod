"""ALSA device enumeration.

Parses `aplay -l` (concise, hw: addressable). Each entry maps to a
`hw:CARD,DEV` device string usable directly with `alsasink device=...`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import List


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
