"""Album art fetching, caching, and half-block terminal rendering."""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from io import BytesIO
from typing import Callable, Optional, TYPE_CHECKING
from urllib.request import urlopen

import numpy as np
from PIL import Image
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widget import Widget

if TYPE_CHECKING:
    from .player import Player

logger = logging.getLogger(__name__)


class AlbumArtCache:
    """In-memory LRU cache for album art PIL images."""

    def __init__(self, max_size: int = 16) -> None:
        self._max_size = max_size
        self._images: OrderedDict[str, Image.Image] = OrderedDict()
        self._lock = threading.Lock()

    def store(self, album_id: str, image_bytes: bytes) -> None:
        """Decode and store raw image bytes."""
        try:
            img = Image.open(BytesIO(image_bytes)).convert("RGB")
        except Exception:
            logger.debug("Failed to decode image for %s", album_id)
            return
        with self._lock:
            if album_id in self._images:
                self._images.move_to_end(album_id)
            else:
                self._images[album_id] = img
                if len(self._images) > self._max_size:
                    self._images.popitem(last=False)
            self._images[album_id] = img

    def get(self, album_id: str, width: int, height: int) -> Optional[np.ndarray]:
        """Return resized pixel array (height, width, 3) or None."""
        with self._lock:
            img = self._images.get(album_id)
            if img is None:
                return None
            self._images.move_to_end(album_id)
        resized = img.resize((width, height), Image.LANCZOS)
        return np.asarray(resized, dtype=np.uint8)

    def has(self, album_id: str) -> bool:
        with self._lock:
            return album_id in self._images

    def fetch_async(
        self,
        album_id: str,
        url: str,
        callback: Callable[[str, bool], None],
    ) -> None:
        """Fetch image in a background thread; call callback(album_id, success)."""

        def _worker() -> None:
            try:
                with urlopen(url) as resp:
                    data = resp.read()
                self.store(album_id, data)
                callback(album_id, True)
            except Exception:
                logger.debug("Failed to fetch art for %s: %s", album_id, url)
                callback(album_id, False)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()


_shared_cache = AlbumArtCache(max_size=16)


class AlbumArtWidget(Widget):
    """Renders a pixel array as Unicode half-block characters."""

    DEFAULT_CSS = """
    AlbumArtWidget {
        height: auto;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._pixels: Optional[np.ndarray] = None

    def set_pixels(self, pixels: Optional[np.ndarray]) -> None:
        self._pixels = pixels
        self.refresh()

    def render_line(self, y: int) -> Strip:
        width = self._size.width
        height = self._size.height
        if width <= 0 or height <= 0:
            return Strip.blank(width)

        pixels = self._pixels
        if pixels is None:
            return Strip.blank(width)

        img_rows, img_cols = pixels.shape[0], pixels.shape[1]
        expected_pixel_rows = height * 2
        if img_rows < expected_pixel_rows or img_cols == 0:
            return Strip.blank(width)

        top_y = y * 2
        bot_y = y * 2 + 1
        if top_y >= img_rows or bot_y >= img_rows:
            return Strip.blank(width)

        # Center the image if narrower than widget
        pad_left = max(0, (width - img_cols) // 2)
        pad_right = max(0, width - img_cols - pad_left)

        segments: list[Segment] = []
        if pad_left > 0:
            segments.append(Segment(" " * pad_left))

        top_row = pixels[top_y]
        bot_row = pixels[bot_y]
        for x in range(img_cols):
            tr, tg, tb = int(top_row[x, 0]), int(top_row[x, 1]), int(top_row[x, 2])
            br, bg, bb = int(bot_row[x, 0]), int(bot_row[x, 1]), int(bot_row[x, 2])
            style = Style(
                color=f"rgb({tr},{tg},{tb})",
                bgcolor=f"rgb({br},{bg},{bb})",
            )
            segments.append(Segment("▀", style))

        if pad_right > 0:
            segments.append(Segment(" " * pad_right))

        return Strip(segments, width)


class AlbumArtVisualizer(Widget):
    """Displays album art as a half-block pixel image, centered."""

    DISPLAY_NAME = "Album Art"
    FPS = 2

    DEFAULT_CSS = """
    AlbumArtVisualizer {
        height: 1fr;
        min-height: 6;
        padding: 0 1;
    }
    """

    def __init__(self, player: "Player") -> None:
        super().__init__()
        self._player = player
        self._pixels: Optional[np.ndarray] = None
        self._current_album_id: Optional[str] = None
        self._cache = _shared_cache

    def on_mount(self) -> None:
        self.set_interval(1 / self.FPS, self._tick)

    def _tick(self) -> None:
        track = self._player._current
        album = getattr(track, "album", None) if track else None
        album_id = str(album.id) if album else None

        if album_id != self._current_album_id:
            self._current_album_id = album_id
            self._pixels = None
            self.refresh()
            if album_id and album:
                try:
                    url = album.image(320)
                except Exception:
                    return
                self._cache.fetch_async(album_id, url, self._on_art_fetched)
        elif album_id and self._pixels is None and self._cache.has(album_id):
            self._render_from_cache(album_id)

    def _on_art_fetched(self, album_id: str, success: bool) -> None:
        if not success or album_id != self._current_album_id:
            return
        try:
            self.app.call_from_thread(self._render_from_cache, album_id)
        except Exception:
            pass

    def _render_from_cache(self, album_id: str) -> None:
        width = self.size.width
        height = self.size.height
        if width <= 0 or height <= 0:
            return
        # Square art, constrained by available space
        side_cols = min(width, height * 2)
        side_rows = side_cols
        pixels = self._cache.get(album_id, width=side_cols, height=side_rows)
        if pixels is not None:
            self._pixels = pixels
            self.refresh()

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        height = self.size.height
        if width <= 0 or height <= 0:
            return Strip.blank(width)

        pixels = self._pixels
        if pixels is None:
            return Strip.blank(width)

        img_pixel_rows = pixels.shape[0]
        img_cols = pixels.shape[1]
        img_cell_rows = img_pixel_rows // 2

        # Vertically center
        v_pad = max(0, (height - img_cell_rows) // 2)
        img_y = y - v_pad
        if img_y < 0 or img_y >= img_cell_rows:
            return Strip.blank(width)

        top_y = img_y * 2
        bot_y = img_y * 2 + 1
        if top_y >= img_pixel_rows or bot_y >= img_pixel_rows:
            return Strip.blank(width)

        # Horizontally center
        pad_left = max(0, (width - img_cols) // 2)
        pad_right = max(0, width - img_cols - pad_left)

        segments: list[Segment] = []
        if pad_left > 0:
            segments.append(Segment(" " * pad_left))

        top_row = pixels[top_y]
        bot_row = pixels[bot_y]
        for x in range(img_cols):
            tr, tg, tb = int(top_row[x, 0]), int(top_row[x, 1]), int(top_row[x, 2])
            br, bg, bb = int(bot_row[x, 0]), int(bot_row[x, 1]), int(bot_row[x, 2])
            style = Style(
                color=f"rgb({tr},{tg},{tb})",
                bgcolor=f"rgb({br},{bg},{bb})",
            )
            segments.append(Segment("▀", style))

        if pad_right > 0:
            segments.append(Segment(" " * pad_right))

        return Strip(segments, width)
