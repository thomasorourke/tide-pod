"""Tests for Player's queue/history bookkeeping (no actual playback)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from tide_pod.player import Player


@dataclass
class FakeTrack:
    id: int
    name: str = "track"
    available: bool = True


@pytest.fixture
def player(monkeypatch: pytest.MonkeyPatch) -> Player:
    # Avoid actually loading streams: stub the worker that fetches MPD/BTS.
    p = Player("hw:99,0")
    monkeypatch.setattr(p, "_start", lambda track, gapless=False: None)
    yield p
    p.shutdown()


def test_play_tracks_sets_queue_and_history(player: Player) -> None:
    tracks = [FakeTrack(i) for i in range(5)]
    player.play_tracks(tracks, start_index=2)
    # _start is stubbed — _current is only set in _apply_uri which we skip.
    assert [t.id for t in player._queue] == [3, 4]
    assert [t.id for t in player._history] == [0, 1]


def test_play_tracks_clamps_start_index(player: Player) -> None:
    tracks = [FakeTrack(i) for i in range(3)]
    player.play_tracks(tracks, start_index=100)
    # Last track becomes the "playing" one — queue empty, all prior in history.
    assert player._queue == []
    assert [t.id for t in player._history] == [0, 1]


def test_play_tracks_empty_is_noop(player: Player) -> None:
    player.play_tracks([])
    assert player._queue == []
    assert player._history == []


def test_next_advances_through_queue(player: Player) -> None:
    tracks = [FakeTrack(i) for i in range(3)]
    player.play_tracks(tracks, start_index=0)
    # Manually mark current (would normally be set by _apply_uri).
    player._current = tracks[0]
    assert player.next() is True
    assert [t.id for t in player._history] == [0]
    assert [t.id for t in player._queue] == [2]


def test_next_at_end_of_queue_returns_false(player: Player) -> None:
    tracks = [FakeTrack(i) for i in range(2)]
    player.play_tracks(tracks, start_index=1)
    player._current = tracks[1]
    # No more tracks queued.
    assert player.next() is False
    # State should be unchanged.
    assert player._queue == []
    assert player._current.id == 1


def test_previous_returns_false_at_start_of_playlist(player: Player) -> None:
    tracks = [FakeTrack(i) for i in range(3)]
    player.play_tracks(tracks, start_index=0)
    player._current = tracks[0]
    # _query_position_ns will return 0 (no track actually playing).
    assert player.previous() is False


def test_previous_pops_history(player: Player) -> None:
    tracks = [FakeTrack(i) for i in range(3)]
    player.play_tracks(tracks, start_index=1)  # history=[0], queue=[2]
    player._current = tracks[1]
    assert player.previous() is True
    assert [t.id for t in player._queue] == [1, 2]
    assert player._history == []


def test_play_track_singular_clears_queue(player: Player) -> None:
    tracks = [FakeTrack(i) for i in range(3)]
    player.play_tracks(tracks, start_index=0)
    assert player._queue
    player.play_track(FakeTrack(99))
    assert player._queue == []
    assert player._history == []
