"""Album view: tracklist with playback."""

from __future__ import annotations

from typing import List

import tidalapi
from tidalapi.album import Album
from tidalapi.media import Track

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, Static

from ..config import LastPlayed


def _fmt_duration(seconds: int) -> str:
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


class AlbumScreen(Screen):
    """Tracklist of an album. Enter plays the selected track in album order."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("enter", "play", "Play"),
        ("space", "toggle", "Play/Pause"),
        ("n", "next", "Next"),
        ("b", "prev", "Prev"),
        ("q", "app.quit", "Quit"),
    ]

    def __init__(self, session: tidalapi.Session, album: Album) -> None:
        super().__init__()
        self.session = session
        self.album = album
        self.tracks: List[Track] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="album-body"):
            artist = getattr(self.album.artist, "name", "")
            yield Label(f"[b]{self.album.name}[/]  —  {artist}", id="album-title")
            yield Static(
                f"{self.album.num_tracks} tracks · {self.album.release_date or ''}",
                id="album-meta",
            )
            table = DataTable(id="tracks", cursor_type="row", zebra_stripes=True)
            table.add_columns("#", "Title", "Artist", "Duration")
            yield table
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._load, thread=True, exclusive=True)

    def _load(self) -> None:
        try:
            tracks = self.album.tracks()
        except Exception as exc:
            self.app.call_from_thread(self._show_error, f"Failed to load album: {exc}")
            return
        self.tracks = list(tracks)
        self.app.call_from_thread(self._populate_tracks)

    def _populate_tracks(self) -> None:
        table = self.query_one("#tracks", DataTable)
        table.clear()
        for i, t in enumerate(self.tracks, 1):
            table.add_row(
                str(i),
                t.name + ("" if t.available else "  (unavailable)"),
                getattr(t.artist, "name", ""),
                _fmt_duration(t.duration),
                key=str(i - 1),
            )
        table.focus()

    def _show_error(self, msg: str) -> None:
        self.query_one("#album-meta", Static).update(f"[red]{msg}[/]")

    # ----- actions -----
    def action_play(self) -> None:
        table = self.query_one("#tracks", DataTable)
        if table.cursor_row is None or table.cursor_row < 0 or not self.tracks:
            return
        idx = table.cursor_row
        self.app.player.play_tracks(self.tracks, start_index=idx)
        # Remember this album as the most-recently-played thing.
        self.app.state.last_played = LastPlayed(
            kind="album",
            id=str(self.album.id),
            name=self.album.name,
            artist=getattr(self.album.artist, "name", ""),
            track_index=idx,
        )
        try:
            self.app.state.save()
        except Exception:
            pass

    def action_toggle(self) -> None:
        if self.app.player:
            self.app.player.toggle()

    def action_next(self) -> None:
        if self.app.player and not self.app.player.next():
            self.notify("No next track.", timeout=1.5)

    def action_prev(self) -> None:
        if self.app.player and not self.app.player.previous():
            self.notify("No previous track.", timeout=1.5)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_play()
