"""Tests for tide_pod.devices — aplay output parsing."""

from __future__ import annotations

from tide_pod.devices import AlsaDevice, parse_aplay_output


# Sample taken from the real `aplay -l` output on a Linux system.
SAMPLE = """\
**** List of PLAYBACK Hardware Devices ****
card 0: Audio [USB Audio], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 0: Audio [USB Audio], device 1: USB Audio [USB Audio #1]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 2: NVidia [HDA NVidia], device 3: HDMI 0 [ROG PG279Q]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 3: USB [Schiit Bifrost 2 Unison USB], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""


def test_parse_basic() -> None:
    devs = parse_aplay_output(SAMPLE)
    assert len(devs) == 4
    bifrost = devs[-1]
    assert bifrost.card == 3
    assert bifrost.device == 0
    assert "Schiit" in bifrost.card_name


def test_address_format() -> None:
    d = AlsaDevice(card=3, device=0, card_name="Schiit", device_name="USB Audio")
    assert d.address == "hw:3,0"


def test_label_format() -> None:
    d = AlsaDevice(card=2, device=3, card_name="HDA NVidia", device_name="ROG PG279Q")
    assert d.address in d.label
    assert "HDA NVidia" in d.label
    assert "ROG PG279Q" in d.label


def test_empty_input() -> None:
    assert parse_aplay_output("") == []


def test_skips_unrelated_lines() -> None:
    text = "garbage\nnot matching\n  Subdevices: 1/1\n"
    assert parse_aplay_output(text) == []


def test_multiple_devices_same_card() -> None:
    devs = parse_aplay_output(SAMPLE)
    card0_devices = [d for d in devs if d.card == 0]
    assert len(card0_devices) == 2
    assert {d.device for d in card0_devices} == {0, 1}
