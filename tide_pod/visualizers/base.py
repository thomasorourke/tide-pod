"""Base class for visualizer widgets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widget import Widget

if TYPE_CHECKING:
    from ..player import Player


class Visualizer(Widget):
    """Base class for full-screen analyzer widgets.

    Subclasses implement `_tick()` (pull data + refresh) and `render_line()`.
    A 60 Hz timer drives _tick.
    """

    DEFAULT_CSS = """
    Visualizer {
        height: 1fr;
        min-height: 6;
        padding: 0 1;
    }
    """
    FPS = 60
    DISPLAY_NAME = "visualizer"

    def __init__(self, player: "Player") -> None:
        super().__init__()
        self._player = player

    def on_mount(self) -> None:
        self.set_interval(1 / self.FPS, self._tick)

    def _tick(self) -> None:  # pragma: no cover - subclassed
        self.refresh()
