"""Album art fetching, caching, and half-block terminal rendering."""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from io import BytesIO
from typing import Callable, Optional
from urllib.request import urlopen

import numpy as np
from PIL import Image
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widget import Widget

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
