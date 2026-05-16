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
