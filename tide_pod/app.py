"""Textual app: search + browse + now-playing footer."""

from __future__ import annotations

import logging
from typing import List, Optional

import tidalapi
from tidalapi.album import Album
from tidalapi.artist import Artist
from tidalapi.media import Track
from tidalapi.playlist import Playlist

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Static,
    TabbedContent,
    TabPane,
)

from . import auth, devices
from .config import Config, LastPlayed, State
from .player import NowPlaying, Player
from .screens.album import AlbumScreen
from .screens.device_picker import DevicePickerScreen
from .screens.login import LoginScreen
from .screens.now_playing import NowPlayingScreen

logger = logging.getLogger(__name__)


def _fmt_time_ns(ns: int) -> str:
    seconds = max(0, int(ns / 1_000_000_000))
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def _fmt_duration(seconds: int) -> str:
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


_QUALITY_LABELS = {
    "LOW": "AAC 96k (lossy)",
    "HIGH": "AAC 320k (lossy)",
    "LOSSLESS": "FLAC (lossless)",
    "HI_RES_LOSSLESS": "FLAC (hi-res lossless)",
}


def _fmt_alsa_format(np: NowPlaying) -> str:
    parts = []
    if np.bit_depth:
        parts.append(f"{np.bit_depth}-bit")
    if np.sample_rate:
        parts.append(f"{np.sample_rate / 1000:g} kHz")
    if np.channels:
        parts.append(f"{np.channels}ch")
    return " / ".join(parts) if parts else "—"


def _fmt_source(np: NowPlaying) -> str:
    label = _QUALITY_LABELS.get(np.source_quality, np.source_quality or "—")
    spec = []
    if np.source_bit_depth:
        spec.append(f"{np.source_bit_depth}-bit")
    if np.source_sample_rate:
        spec.append(f"{np.source_sample_rate / 1000:g} kHz")
    if spec:
        return f"{label}  {' / '.join(spec)}"
    return label


class NowPlayingBar(Static):
    """Now-playing footer: track + source format + ALSA output format."""

    state: reactive[NowPlaying] = reactive(NowPlaying, layout=True)
    # Set at launch when there's a remembered last-played item but the
    # pipeline hasn't been touched yet. Shown instead of "Not playing" so
    # the user knows pressing space will resume that item.
    pending_resume: reactive[Optional[LastPlayed]] = reactive(None, layout=True)

    def render(self) -> str:
        np = self.state
        if np.track is None:
            lp = self.pending_resume
            if lp is not None and lp.is_set():
                who = f"  —  {lp.artist}" if lp.artist else ""
                return (
                    f"⏸  [b]{lp.name}[/]{who}   [dim]· last {lp.kind}[/]\n"
                    f"[dim]Press space to resume.[/]"
                )
            return "[dim]Not playing[/]"
        artist = getattr(np.track.artist, "name", "")
        album = getattr(np.track.album, "name", "") if np.track.album else ""
        title = np.track.name
        play_icon = "▶" if np.playing else "⏸"
        time_str = f"{_fmt_time_ns(np.position_ns)} / {_fmt_time_ns(np.duration_ns)}"

        # Bit-perfect badge when source and ALSA rate/depth match.
        bp = (
            np.source_sample_rate
            and np.source_bit_depth
            and np.sample_rate == np.source_sample_rate
            and np.bit_depth == np.source_bit_depth
        )
        badge = "[green b]bit-perfect[/]" if bp else "[yellow]converted[/]"

        line1 = f"{play_icon}  [b]{title}[/]  —  {artist}"
        if album:
            line1 += f"   [dim]· {album}[/]"
        line1 += f"   [dim]{time_str}[/]"

        line2 = (
            f"[dim]Source:[/] {_fmt_source(np)}    "
            f"[dim]Out:[/] [b]{np.alsa_device or '?'}[/] {_fmt_alsa_format(np)}    "
            f"{badge}"
        )
        return f"{line1}\n{line2}"


class TidePodApp(App):
    """Main Textual application."""

    TITLE = "tide-pod"
    SUB_TITLE = "Delicious audio."

    CSS = """
    Screen { layout: vertical; }
    #search-row { height: auto; padding: 0 1; }
    #search-input { width: 1fr; }
    TabbedContent { height: 1fr; }
    DataTable { height: 1fr; }
    NowPlayingBar {
        height: 3;
        padding: 0 1;
        background: $boost;
        border-top: solid $accent;
    }
    #login-box, #picker-box { width: 70; padding: 2 4; border: round $accent; }
    #title { text-style: bold; }
    #code { text-style: bold; padding: 1 0; }
    #url { padding: 1 0; }
    """

    BINDINGS = [
        ("/", "focus_search", "Search"),
        ("f", "now_playing", "Now Playing"),
        ("r", "resume_last", "Resume last"),
        ("space", "toggle", "Play/Pause"),
        ("n", "next", "Next"),
        ("b", "prev", "Prev"),
        ("ctrl+d", "change_output", "Change output"),
        ("ctrl+l", "logout", "Logout"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config: Config = Config.load()
        self.state: State = State.load()
        self.session: tidalapi.Session = auth.new_session(self.config)
        self.player: Optional[Player] = None
        self._poll_timer = None

    # ---- composition --------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="search-row"):
            yield Input(placeholder="Search artists, albums, tracks …  (press /)", id="search-input")
        with TabbedContent(initial="albums-tab", id="results-tabs"):
            with TabPane("Albums", id="albums-tab"):
                albums = DataTable(id="albums-table", cursor_type="row", zebra_stripes=True)
                albums.add_columns("Title", "Artist", "Year", "Tracks")
                yield albums
            with TabPane("Tracks", id="tracks-tab"):
                tracks = DataTable(id="tracks-table", cursor_type="row", zebra_stripes=True)
                tracks.add_columns("Title", "Artist", "Album", "Duration")
                yield tracks
            with TabPane("Artists", id="artists-tab"):
                artists = DataTable(id="artists-table", cursor_type="row", zebra_stripes=True)
                artists.add_columns("Artist")
                yield artists
            with TabPane("Playlists", id="playlists-tab"):
                playlists = DataTable(id="playlists-table", cursor_type="row", zebra_stripes=True)
                playlists.add_columns("Title", "Creator", "Tracks")
                yield playlists
        yield NowPlayingBar(id="now-playing")
        yield Footer()

    # ---- lifecycle ----------------------------------------------------
    def on_mount(self) -> None:
        # push_screen_wait requires a worker context, so the whole bootstrap
        # flow (resume-session -> login screen -> device picker) runs there.
        self.run_worker(self._bootstrap(), exclusive=True)

    async def _bootstrap(self) -> None:
        if not auth.try_resume(self.session):
            result = await self.push_screen_wait(LoginScreen(self.session))
            if not result:
                self.exit()
                return
        await self._after_login()

    async def _after_login(self) -> None:
        # Figure out which audio output to use. Two modes:
        #   - "pulse": shared via PulseAudio/PipeWire; no device lookup needed.
        #   - "alsa": exclusive hw:CARD,DEV. Card numbering shifts when USB
        #     devices are plugged in different orders, so we pin by card name
        #     and resolve to the current hw: index each launch.
        backend = self.config.audio_backend
        alsa_address = ""
        need_picker = False
        if backend == "pulse":
            pass  # ready to go
        elif backend == "alsa" and self.config.alsa_card_name:
            resolved = devices.resolve(
                self.config.alsa_card_name, self.config.alsa_device_index
            )
            if resolved is None:
                self.notify(
                    f"Saved audio device “{self.config.alsa_card_name}” not found. "
                    "Pick another.",
                    severity="warning",
                    timeout=4,
                )
                need_picker = True
            else:
                alsa_address = resolved.address
        else:
            need_picker = True
        if need_picker:
            choice = await self.push_screen_wait(
                DevicePickerScreen(
                    current_backend=self.config.audio_backend,
                    current_card_name=self.config.alsa_card_name,
                    current_device_index=self.config.alsa_device_index,
                )
            )
            if choice is None:
                self.exit()
                return
            backend = choice.backend
            self.config.audio_backend = backend
            if choice.backend == "alsa" and choice.alsa is not None:
                self.config.alsa_card_name = choice.alsa.card_name
                self.config.alsa_device_index = choice.alsa.device
                alsa_address = choice.alsa.address
            else:
                # Pulse mode — clear any stale alsa pin.
                self.config.alsa_card_name = ""
                self.config.alsa_device_index = 0
            self.config.save()
        # Spin up the player now that we have an output.
        self.player = Player(
            alsa_address,
            vis_offset_ms=self.config.vis_offset_ms,
            backend=backend,
        )
        self.player.on_state_changed = self._on_player_state
        self.player.on_track_changed = self._on_player_state
        self.player.on_error = self._on_player_error
        self._poll_timer = self.set_interval(0.5, self._tick)
        # Textual auto-focuses the first focusable widget (the search Input);
        # nudge focus onto the results table so arrow keys / space / r work
        # without typing into the search box. Press / to focus search.
        self.query_one("#albums-table", DataTable).focus()
        # Surface the last-played item in the footer. We don't preload it
        # into the pipeline — PAUSED on a bit-perfect hw: alsasink doesn't
        # cleanly hand off to PLAYING — so resume waits until the user
        # presses space or `r`.
        if self.state.last_played.is_set():
            self.query_one(NowPlayingBar).pending_resume = self.state.last_played

    # ---- search -------------------------------------------------------
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "search-input":
            return
        query = event.value.strip()
        if not query:
            return
        self.notify(f"Searching for “{query}” …", timeout=1.5)
        self.run_worker(lambda q=query: self._do_search(q), thread=True, exclusive=True)

    def _do_search(self, query: str) -> None:
        try:
            results = self.session.search(query, [Artist, Album, Playlist, Track], 25)
        except Exception as exc:
            self.call_from_thread(self.notify, f"Search failed: {exc}", severity="error")
            return
        self.call_from_thread(self._render_search, results)

    def _render_search(self, results: dict) -> None:
        # tracks
        tracks: List[Track] = list(results.get("tracks") or [])
        t_table = self.query_one("#tracks-table", DataTable)
        t_table.clear()
        for i, t in enumerate(tracks):
            t_table.add_row(
                t.name + ("" if t.available else "  (unavailable)"),
                getattr(t.artist, "name", ""),
                getattr(t.album, "name", "") if t.album else "",
                _fmt_duration(t.duration),
                key=str(i),
            )
        t_table._tide_items = tracks  # type: ignore[attr-defined]

        # albums
        albums: List[Album] = list(results.get("albums") or [])
        a_table = self.query_one("#albums-table", DataTable)
        a_table.clear()
        for i, a in enumerate(albums):
            a_table.add_row(
                a.name,
                getattr(a.artist, "name", ""),
                str(a.year) if getattr(a, "year", None) else "",
                str(a.num_tracks or ""),
                key=str(i),
            )
        a_table._tide_items = albums  # type: ignore[attr-defined]

        # artists
        artists: List[Artist] = list(results.get("artists") or [])
        ar_table = self.query_one("#artists-table", DataTable)
        ar_table.clear()
        for i, ar in enumerate(artists):
            ar_table.add_row(ar.name, key=str(i))
        ar_table._tide_items = artists  # type: ignore[attr-defined]

        # playlists
        playlists: List[Playlist] = list(results.get("playlists") or [])
        p_table = self.query_one("#playlists-table", DataTable)
        p_table.clear()
        for i, p in enumerate(playlists):
            p_table.add_row(
                p.name,
                getattr(p.creator, "name", "") if getattr(p, "creator", None) else "",
                str(getattr(p, "num_tracks", "") or ""),
                key=str(i),
            )
        p_table._tide_items = playlists  # type: ignore[attr-defined]

    # ---- table activation --------------------------------------------
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table = event.data_table
        items = getattr(table, "_tide_items", None)
        if not items:
            return
        idx = event.cursor_row
        if idx is None or idx < 0 or idx >= len(items):
            return
        item = items[idx]
        if isinstance(item, Track):
            if self.player and item.available:
                self.player.play_tracks(items, start_index=idx)
                self._remember_track(item)
        elif isinstance(item, Album):
            self.push_screen(AlbumScreen(self.session, item))
        elif isinstance(item, Artist):
            if self.player:
                try:
                    tops = list(item.get_top_tracks()) if hasattr(item, "get_top_tracks") else list(item.top_tracks())
                except Exception as exc:
                    self.notify(f"Couldn't load artist tracks: {exc}", severity="error")
                    return
                if tops:
                    self.player.play_tracks(tops)
                    self._remember(
                        LastPlayed(kind="artist", id=str(item.id), name=item.name)
                    )
        elif isinstance(item, Playlist):
            if self.player:
                try:
                    tracks = list(item.tracks())
                except Exception as exc:
                    self.notify(f"Couldn't load playlist: {exc}", severity="error")
                    return
                if tracks:
                    self.player.play_tracks(tracks)
                    self._remember(
                        LastPlayed(
                            kind="playlist",
                            id=str(item.id),
                            name=item.name,
                            artist=getattr(item.creator, "name", "") if getattr(item, "creator", None) else "",
                        )
                    )

    # ---- state persistence ------------------------------------------
    def _remember(self, lp: LastPlayed) -> None:
        self.state.last_played = lp
        try:
            self.state.save()
        except Exception:
            pass

    def _remember_track(self, track: Track) -> None:
        album = track.album
        if album is not None:
            self._remember(
                LastPlayed(
                    kind="album",
                    id=str(album.id),
                    name=album.name,
                    artist=getattr(album.artist, "name", ""),
                )
            )
        else:
            self._remember(
                LastPlayed(
                    kind="track",
                    id=str(track.id),
                    name=track.name,
                    artist=getattr(track.artist, "name", ""),
                )
            )

    # ---- player wiring -----------------------------------------------
    def _on_player_state(self, np: NowPlaying) -> None:
        # call_from_thread raises if invoked from the app's main thread.
        # Most player callbacks come from the GLib mainloop thread (safe),
        # but fall back to a direct call if not — never crash here.
        try:
            self.call_from_thread(self._update_now_playing, np)
        except RuntimeError:
            self._update_now_playing(np)

    def _on_player_error(self, msg: str) -> None:
        try:
            self.call_from_thread(self.notify, msg, severity="error")
        except RuntimeError:
            self.notify(msg, severity="error")

    def _update_now_playing(self, np: NowPlaying) -> None:
        try:
            self.query_one(NowPlayingBar).state = np
        except Exception:
            # NowPlayingBar may not be in the current screen (e.g. on the
            # full-screen Now Playing view) and we can race with shutdown.
            pass

    def _tick(self) -> None:
        if self.player is None:
            return
        try:
            self.query_one(NowPlayingBar).state = self.player.snapshot()
        except Exception:
            pass

    # ---- actions ------------------------------------------------------
    def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()

    def action_now_playing(self) -> None:
        if self.player is None:
            return
        self.push_screen(NowPlayingScreen())

    def action_resume_last(self) -> None:
        lp = self.state.last_played
        if not lp.is_set() or self.player is None:
            self.notify("Nothing recent to resume yet.", timeout=2)
            return
        self.notify(f"Resuming {lp.kind}: {lp.name}", timeout=2)
        self.run_worker(self._do_resume, thread=True, exclusive=True)

    def _do_resume(self) -> None:
        lp = self.state.last_played
        try:
            if lp.kind == "album":
                obj = self.session.album(int(lp.id))
                tracks = list(obj.tracks())
            elif lp.kind == "playlist":
                obj = self.session.playlist(lp.id)
                tracks = list(obj.tracks())
            elif lp.kind == "artist":
                obj = self.session.artist(int(lp.id))
                tracks = list(obj.get_top_tracks()) if hasattr(obj, "get_top_tracks") else list(obj.top_tracks())
            elif lp.kind == "track":
                obj = self.session.track(int(lp.id))
                tracks = [obj]
            else:
                tracks = []
        except Exception as exc:
            self.call_from_thread(self.notify, f"Couldn't resume: {exc}", severity="error")
            return
        if not tracks:
            return
        if self.player is not None:
            self.player.play_tracks(tracks)

    def action_toggle(self) -> None:
        if self.player is None:
            return
        # Nothing loaded yet but we have a remembered item: resume it on
        # the first space press instead of doing nothing.
        if self.player.snapshot().track is None and self.state.last_played.is_set():
            self.action_resume_last()
            return
        self.player.toggle()

    def action_next(self) -> None:
        if self.player and not self.player.next():
            self.notify("No next track.", timeout=1.5)

    def action_prev(self) -> None:
        if self.player and not self.player.previous():
            self.notify("No previous track.", timeout=1.5)

    def action_change_output(self) -> None:
        """Re-open the device picker; tear down and rebuild the player."""
        if self.player is None:
            return
        # push_screen_wait must be awaited from a worker context.
        self.run_worker(self._do_change_output(), exclusive=True)

    async def _do_change_output(self) -> None:
        choice = await self.push_screen_wait(
            DevicePickerScreen(
                current_backend=self.config.audio_backend,
                current_card_name=self.config.alsa_card_name,
                current_device_index=self.config.alsa_device_index,
            )
        )
        if choice is None:
            return
        self.player.shutdown()
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        address = ""
        self.config.audio_backend = choice.backend
        if choice.backend == "alsa" and choice.alsa is not None:
            self.config.alsa_card_name = choice.alsa.card_name
            self.config.alsa_device_index = choice.alsa.device
            address = choice.alsa.address
        else:
            self.config.alsa_card_name = ""
            self.config.alsa_device_index = 0
        self.config.save()
        self.player = Player(
            address,
            vis_offset_ms=self.config.vis_offset_ms,
            backend=choice.backend,
        )
        self.player.on_state_changed = self._on_player_state
        self.player.on_track_changed = self._on_player_state
        self.player.on_error = self._on_player_error
        self._poll_timer = self.set_interval(0.5, self._tick)
        label = "PulseAudio (shared)" if choice.backend == "pulse" else address
        self.notify(f"Output: {label}. Press r to resume.", timeout=2)

    async def action_logout(self) -> None:
        auth.logout()
        self.notify("Logged out. Restart tide-pod to sign in again.")
        self.exit()

    def on_unmount(self) -> None:
        if self.player:
            self.player.shutdown()
