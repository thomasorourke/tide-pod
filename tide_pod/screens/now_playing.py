"""Full-screen Now Playing view with pluggable visualizers."""

from __future__ import annotations

import math
from typing import List, TYPE_CHECKING

import numpy as np
from rich.align import Align
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.segment import Segment
from rich.style import Style
from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Container
from textual.reactive import reactive
from textual.screen import Screen
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Footer, Header, Static

from ..player import NowPlaying

if TYPE_CHECKING:  # pragma: no cover
    from ..player import Player


_GST_SECOND = 1_000_000_000


def _fmt_time(seconds: float) -> str:
    s = max(0, int(seconds))
    m, s = divmod(s, 60)
    return f"{m}:{s:02d}"


# --- shared rendering primitives ---------------------------------------------

_BLOCKS = (" ", "▁", "▂", "▃", "▄", "▅", "▆", "▇", "█")
_HBLOCKS = (" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉", "█")  # 8 partial-fill horiz

_STYLE_GREEN = Style(color="green")
_STYLE_YELLOW = Style(color="yellow")
_STYLE_RED = Style(color="red")
_STYLE_BRIGHT_RED = Style(color="bright_red", bold=True)
_STYLE_DIM = Style(color="grey42")


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
    # Render rate. Data updates faster than this (FFT hop is ~90 Hz), so
    # every frame gets fresh data. The widget applies EMA smoothing between
    # data updates so motion stays smooth even at high FPS.
    FPS = 60
    DISPLAY_NAME = "visualizer"

    def __init__(self, player: "Player") -> None:
        super().__init__()
        self._player = player

    def on_mount(self) -> None:
        self.set_interval(1 / self.FPS, self._tick)

    def _tick(self) -> None:  # pragma: no cover - subclassed
        self.refresh()


# --- Spectrum analyzer -------------------------------------------------------

class SpectrumVisualizer(Visualizer):
    """Log-frequency FFT bars. Bass on the left, treble on the right."""

    DISPLAY_NAME = "Spectrum"

    # Attack/release smoothing: each render frame, bar moves toward the new
    # FFT value by α (1 = snap instantly, 0 = never move). Tuned for 60 fps.
    # The bigger FFT window already smooths the source; here we just keep
    # motion fluid between frames.
    ATTACK = 0.75  # snap toward peaks in ~3 frames (~50 ms)
    RELEASE = 0.30  # decay in ~10 frames (~165 ms) — smooth, not laggy
    GAMMA = 0.55
    REVERSED = False  # False = bass left (standard)

    def __init__(self, player: "Player") -> None:
        super().__init__(player)
        self._bars = np.zeros(1, dtype=np.float32)
        self._idx_lo = np.zeros(1, dtype=np.int32)
        self._idx_hi = np.zeros(1, dtype=np.int32)
        self._idx_for_width = 0
        self._idx_for_bands = 0

    def _rebuild_indices(self, bands: int, cols: int) -> None:
        start = 1  # skip DC
        end = bands
        log_lo = math.log(start)
        log_hi = math.log(end)
        idx_lo = np.empty(cols, dtype=np.int32)
        idx_hi = np.empty(cols, dtype=np.int32)
        prev = start
        for col in range(cols):
            t = (col + 1) / cols
            # Round (not floor) to avoid float drift leaving the last bin
            # one short of `bands`.
            hi = int(round(math.exp(log_lo + (log_hi - log_lo) * t)))
            if hi <= prev:
                hi = prev + 1
            if hi > end:
                hi = end
            idx_lo[col] = prev
            idx_hi[col] = hi
            prev = hi
        # The last column may have rounded down; force it to cover the tail.
        idx_hi[-1] = end
        self._idx_lo = idx_lo
        self._idx_hi = idx_hi
        self._idx_for_width = cols
        self._idx_for_bands = bands

    def _tick(self) -> None:
        width = max(1, self.size.width)
        mags = self._player.spectrum_snapshot()
        if not mags:
            self._bars = np.zeros(width, dtype=np.float32)
            self.refresh()
            return

        arr = np.asarray(mags, dtype=np.float32)
        bands = arr.shape[0]
        if (
            self._idx_for_width != width
            or self._idx_for_bands != bands
            or self._bars.shape[0] != width
        ):
            self._rebuild_indices(bands, width)
            self._bars = np.zeros(width, dtype=np.float32)

        # Vectorized per-column max across band ranges. Indices are
        # contiguous (hi[i] == lo[i+1]) so reduceat covers each range in one
        # pass — way faster than a Python loop.
        out = np.maximum.reduceat(arr, self._idx_lo)
        if out.shape[0] != width:
            out = out[:width]
        np.power(out, self.GAMMA, out=out)
        np.clip(out, 0.0, 1.0, out=out)
        if self.REVERSED:
            out = out[::-1]

        # Attack/release smoothing: rise fast to peaks, fall smoothly.
        prev = self._bars
        rising = out > prev
        attack_val = prev + (out - prev) * self.ATTACK
        release_val = prev + (out - prev) * self.RELEASE
        self._bars = np.where(rising, attack_val, release_val).astype(np.float32)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        height = self.size.height
        if width <= 0 or height <= 0:
            return Strip.blank(width)

        bars = self._bars
        if bars.shape[0] != width:
            return Strip.blank(width, self.rich_style)

        total_sub = height * 8
        row_from_bottom = height - 1 - y
        sub_lo = row_from_bottom * 8
        sub_hi = sub_lo + 8
        mid = sub_lo + 4
        ratio = mid / total_sub
        if ratio < 0.55:
            row_style = _STYLE_GREEN
        elif ratio < 0.8:
            row_style = _STYLE_YELLOW
        else:
            row_style = _STYLE_RED

        chars = []
        filled = (bars * total_sub).round().astype(np.int32)
        for c in range(width):
            f = int(filled[c])
            if f <= sub_lo:
                chars.append(" ")
            elif f >= sub_hi:
                chars.append("█")
            else:
                chars.append(_BLOCKS[f - sub_lo])
        return Strip([Segment("".join(chars), row_style)], width)


# --- VU meters ---------------------------------------------------------------

class VUVisualizer(Visualizer):
    """Vertical L/R amplifier-style meters.

    Two fat columns side-by-side, anchored at the bottom of the widget,
    filling upward as volume rises. Blue gradient from deep navy (bottom)
    to bright cyan-white (top). A bright peak-hold marker rides above the
    RMS fill.
    """

    DISPLAY_NAME = "VU Meters"

    DEFAULT_CSS = """
    VUVisualizer {
        height: 1fr;
        min-height: 8;
        padding: 1 4;
    }
    """

    # Gradient stops (R, G, B) — deep navy → bright sky blue
    GRAD_BOTTOM = (15, 35, 90)
    GRAD_TOP = (180, 230, 255)
    PEAK_RGB = (240, 250, 255)

    # Attack/release smoothing for the displayed RMS bar values. Tuned for
    # the widget's 60 fps tick rate.
    ATTACK = 0.75  # snap up in ~3 frames
    RELEASE = 0.30  # smooth fall, no flicker

    # Smoothed display values, updated each tick via EMA.
    _l_rms = 0.0
    _l_peak = 0.0
    _r_rms = 0.0
    _r_peak = 0.0

    def __init__(self, player: "Player") -> None:
        super().__init__(player)
        # Cached row styles; rebuilt when height changes.
        self._row_styles: List[Style] = []
        self._peak_style = Style(color=f"rgb({self.PEAK_RGB[0]},{self.PEAK_RGB[1]},{self.PEAK_RGB[2]})", bold=True)
        self._dim_bar_style = Style(color="grey15")  # unfilled column shade
        self._label_style = Style(color="grey42")
        self._for_height = 0

    def _ensure_styles(self, height: int) -> None:
        if self._for_height == height and len(self._row_styles) == height:
            return
        b = self.GRAD_BOTTOM
        t = self.GRAD_TOP
        styles: List[Style] = []
        for y in range(height):
            # y=0 is TOP → use GRAD_TOP. y=height-1 is BOTTOM → use GRAD_BOTTOM.
            ratio = (height - 1 - y) / max(1, height - 1)  # 1 at top, 0 at bottom
            r = int(b[0] + (t[0] - b[0]) * ratio)
            g = int(b[1] + (t[1] - b[1]) * ratio)
            bl = int(b[2] + (t[2] - b[2]) * ratio)
            styles.append(Style(color=f"rgb({r},{g},{bl})"))
        self._row_styles = styles
        self._for_height = height

    def _tick(self) -> None:
        l_rms, l_peak, r_rms, r_peak = self._player.vu_snapshot()
        # Attack/release on RMS bars so they don't strobe between hops.
        for cur, name in ((l_rms, "_l_rms"), (r_rms, "_r_rms")):
            prev = getattr(self, name)
            alpha = self.ATTACK if cur > prev else self.RELEASE
            setattr(self, name, prev + (cur - prev) * alpha)
        # Peak marker uses the raw peak (already has its own slow decay in
        # the FFT thread) — don't smooth it further.
        self._l_peak = l_peak
        self._r_peak = r_peak
        self.refresh()

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        height = self.size.height
        if width <= 0 or height <= 0:
            return Strip.blank(width)

        self._ensure_styles(height)

        # Reserve last row for channel labels; bars live in y=0 .. height-2.
        bar_rows = max(1, height - 1)
        is_label_row = y == height - 1

        # Column layout: each meter is ~30% of width with a gap; centered.
        col_w = max(3, int(width * 0.30))
        gap = max(2, int(width * 0.06))
        total = col_w * 2 + gap
        left_x = max(0, (width - total) // 2)
        l_start = left_x
        l_end = l_start + col_w
        r_start = l_end + gap
        r_end = min(width, r_start + col_w)

        if is_label_row:
            row = [" "] * width
            lab_l = "L"
            lab_r = "R"
            lpos = l_start + (col_w - len(lab_l)) // 2
            rpos = r_start + (col_w - len(lab_r)) // 2
            for i, ch in enumerate(lab_l):
                if 0 <= lpos + i < width:
                    row[lpos + i] = ch
            for i, ch in enumerate(lab_r):
                if 0 <= rpos + i < width:
                    row[rpos + i] = ch
            return Strip([Segment("".join(row), self._label_style)], width)

        # For each meter column, decide what this row looks like.
        # RMS fill height in sub-rows of 8.
        total_sub = bar_rows * 8
        l_filled = int(round(self._l_rms * total_sub))
        r_filled = int(round(self._r_rms * total_sub))
        l_peak_row = int(round(self._l_peak * (bar_rows - 1)))  # row from BOTTOM
        r_peak_row = int(round(self._r_peak * (bar_rows - 1)))

        # Current row's vertical sub-row range, anchored at bottom.
        row_from_bottom = bar_rows - 1 - y
        sub_lo = row_from_bottom * 8
        sub_hi = sub_lo + 8

        # Style for this row of the bar (gradient by y).
        row_style = self._row_styles[y]

        def cell_char(filled_sub: int) -> str:
            if filled_sub <= sub_lo:
                return " "
            if filled_sub >= sub_hi:
                return "█"
            return _BLOCKS[filled_sub - sub_lo]

        l_char = cell_char(l_filled)
        r_char = cell_char(r_filled)

        # Peak marker overrides the cell content if this row is the peak row.
        l_is_peak = (row_from_bottom == l_peak_row and self._l_peak > 0.01 and l_filled < sub_lo)
        r_is_peak = (row_from_bottom == r_peak_row and self._r_peak > 0.01 and r_filled < sub_lo)

        # Build the row: spaces outside the columns, fill chars within them.
        segments: List[Segment] = []
        # leading spaces before left column
        if l_start > 0:
            segments.append(Segment(" " * l_start, self._label_style))
        # Left meter column
        if l_is_peak:
            segments.append(Segment("▀" * col_w, self._peak_style))
        else:
            segments.append(Segment(l_char * col_w, row_style if l_char != " " else self._dim_bar_style))
        # Gap
        segments.append(Segment(" " * (r_start - l_end), self._label_style))
        # Right meter column
        if r_is_peak:
            segments.append(Segment("▀" * col_w, self._peak_style))
        else:
            segments.append(Segment(r_char * col_w, row_style if r_char != " " else self._dim_bar_style))
        # Trailing spaces
        if r_end < width:
            segments.append(Segment(" " * (width - r_end), self._label_style))

        return Strip(segments, width)


# --- registry ----------------------------------------------------------------

from ..visualizers.widget import MilkdropVisualizer  # noqa: E402 (deferred to avoid circular import)

# (config-key, display-name, widget-class-or-None). None = visualizer off.
VISUALIZER_OPTIONS = [
    ("spectrum", "Spectrum", SpectrumVisualizer),
    ("vu", "VU Meters", VUVisualizer),
    ("milkdrop", "Milkdrop", MilkdropVisualizer),
    ("off", "Off", None),
]


def visualizer_index_for(key: str) -> int:
    for i, (k, _name, _cls) in enumerate(VISUALIZER_OPTIONS):
        if k == key:
            return i
    return 0


# --- Now Playing screen ------------------------------------------------------

class NowPlayingScreen(Screen):
    """Full-screen Now Playing with title, format details, and a visualizer."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("space", "toggle", "Play/Pause"),
        ("n", "next", "Next"),
        ("b", "prev", "Prev"),
        ("v", "cycle_visualizer", "Visualizer"),
        ("[", "offset_down", "Sync -25 ms"),
        ("]", "offset_up", "Sync +25 ms"),
        ("q", "app.quit", "Quit"),
    ]

    state: reactive[NowPlaying] = reactive(NowPlaying, layout=True)

    DEFAULT_CSS = """
    NowPlayingScreen { layout: vertical; }
    #np-title-pane { height: auto; padding: 1 2; }
    #np-meta { height: auto; padding: 0 2; }
    #np-vis-host { height: 1fr; }
    #np-progress { height: 3; padding: 0 2; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._tick_timer = None
        self._vis_index = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("", id="np-title-pane")
        yield Static("", id="np-meta")
        yield Container(id="np-vis-host")
        yield Static("", id="np-progress")
        yield Footer()

    def on_mount(self) -> None:
        # Pick the saved visualizer from config.
        self._vis_index = visualizer_index_for(self.app.config.visualizer)
        self._mount_visualizer()
        self._tick_timer = self.set_interval(0.25, self._tick)
        self._tick()

    def on_unmount(self) -> None:
        if self._tick_timer is not None:
            self._tick_timer.stop()

    def _mount_visualizer(self) -> None:
        host = self.query_one("#np-vis-host", Container)
        host.remove_children()
        _key, name, cls = VISUALIZER_OPTIONS[self._vis_index]
        if cls is not None:
            host.mount(cls(self.app.player))

    def action_cycle_visualizer(self) -> None:
        self._vis_index = (self._vis_index + 1) % len(VISUALIZER_OPTIONS)
        self._mount_visualizer()
        key, name, _cls = VISUALIZER_OPTIONS[self._vis_index]
        # Persist the choice.
        self.app.config.visualizer = key
        try:
            self.app.config.save()
        except Exception:
            pass
        self.notify(f"Visualizer: {name}", timeout=1.5)

    def _tick(self) -> None:
        if self.app.player is None:
            return
        self.state = self.app.player.snapshot()

    def watch_state(self, np: NowPlaying) -> None:
        self.query_one("#np-title-pane", Static).update(self._title_pane(np))
        self.query_one("#np-meta", Static).update(self._meta_pane(np))
        self.query_one("#np-progress", Static).update(self._progress_pane(np))

    # ---- panes ----
    def _title_pane(self, np: NowPlaying) -> RenderableType:
        if np.track is None:
            return Align.center(Text("Not playing", style="dim"))
        title = Text(np.track.name, style="bold white", justify="center")
        artist = Text(
            getattr(np.track.artist, "name", "") or "",
            style="bold cyan",
            justify="center",
        )
        album = Text(
            getattr(np.track.album, "name", "") if np.track.album else "",
            style="italic dim",
            justify="center",
        )
        return Panel(Group(title, artist, album), border_style="cyan")

    def _meta_pane(self, np: NowPlaying) -> RenderableType:
        from ..app import _QUALITY_LABELS

        bp = (
            np.source_sample_rate
            and np.source_bit_depth
            and np.sample_rate == np.source_sample_rate
            and np.bit_depth == np.source_bit_depth
        )
        badge_text = "BIT-PERFECT" if bp else "CONVERTED"
        badge_style = "bold black on green" if bp else "bold black on yellow"

        source_label = _QUALITY_LABELS.get(np.source_quality, np.source_quality or "—")
        src = f"{source_label}"
        if np.source_bit_depth and np.source_sample_rate:
            src += f"  ·  {np.source_bit_depth}-bit / {np.source_sample_rate/1000:g} kHz"
        alsa = f"{np.alsa_device or '?'}"
        if np.bit_depth and np.sample_rate:
            alsa += f"  ·  {np.bit_depth}-bit / {np.sample_rate/1000:g} kHz / {np.channels}ch"

        body = Text()
        body.append("Source  ", style="dim")
        body.append(src + "\n")
        body.append("ALSA    ", style="dim")
        body.append(alsa + "  ")
        body.append(f" {badge_text} ", style=badge_style)
        return Align.center(body)

    def _progress_pane(self, np: NowPlaying) -> RenderableType:
        pos = np.position_ns / _GST_SECOND if np.position_ns else 0
        dur = np.duration_ns / _GST_SECOND if np.duration_ns else 0
        bar = ProgressBar(total=max(dur, 1), completed=min(pos, dur))
        elapsed = _fmt_time(pos)
        remaining = _fmt_time(max(0, dur - pos))
        line = Text()
        line.append(elapsed + "  ", style="white")
        return Group(line, bar, Text(f"  -{remaining}", style="dim"))

    # ---- actions ----
    def action_toggle(self) -> None:
        if self.app.player:
            self.app.player.toggle()

    def action_next(self) -> None:
        if self.app.player and not self.app.player.next():
            self.notify("No next track.", timeout=1.5)

    def action_prev(self) -> None:
        if self.app.player and not self.app.player.previous():
            self.notify("No previous track.", timeout=1.5)

    def action_offset_up(self) -> None:
        self._nudge_offset(25)

    def action_offset_down(self) -> None:
        self._nudge_offset(-25)

    def _nudge_offset(self, delta_ms: int) -> None:
        if self.app.player is None:
            return
        new_val = max(0, min(1000, self.app.player.vis_offset_ms + delta_ms))
        self.app.player.set_vis_offset_ms(new_val)
        self.app.config.vis_offset_ms = new_val
        try:
            self.app.config.save()
        except Exception:
            pass
        self.notify(f"Visualizer sync offset: {new_val} ms", timeout=1.2)


