"""Tests for album art cache and widget rendering."""

from __future__ import annotations

import threading
from io import BytesIO
from unittest.mock import patch, MagicMock

import numpy as np
import pytest
from PIL import Image

from tide_pod.album_art import AlbumArtCache


def _make_test_image(width: int = 320, height: int = 320) -> bytes:
    """Create a minimal RGB JPEG in memory."""
    img = Image.new("RGB", (width, height), color=(255, 0, 128))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestAlbumArtCache:
    def test_get_returns_none_when_not_cached(self) -> None:
        cache = AlbumArtCache(max_size=4)
        result = cache.get("album-123", width=20, height=20)
        assert result is None

    def test_store_and_get_returns_correct_shape(self) -> None:
        cache = AlbumArtCache(max_size=4)
        img_bytes = _make_test_image(320, 320)
        cache.store("album-123", img_bytes)
        result = cache.get("album-123", width=20, height=20)
        assert result is not None
        assert result.shape == (20, 20, 3)
        assert result.dtype == np.uint8

    def test_get_resizes_to_requested_dimensions(self) -> None:
        cache = AlbumArtCache(max_size=4)
        img_bytes = _make_test_image(320, 320)
        cache.store("album-456", img_bytes)
        r1 = cache.get("album-456", width=40, height=30)
        assert r1 is not None
        assert r1.shape == (30, 40, 3)
        r2 = cache.get("album-456", width=10, height=10)
        assert r2 is not None
        assert r2.shape == (10, 10, 3)

    def test_lru_eviction(self) -> None:
        cache = AlbumArtCache(max_size=2)
        img_bytes = _make_test_image()
        cache.store("a", img_bytes)
        cache.store("b", img_bytes)
        cache.store("c", img_bytes)
        # "a" should be evicted
        assert cache.get("a", width=10, height=10) is None
        assert cache.get("b", width=10, height=10) is not None
        assert cache.get("c", width=10, height=10) is not None

    def test_fetch_async_calls_callback_on_success(self) -> None:
        cache = AlbumArtCache(max_size=4)
        img_bytes = _make_test_image()
        event = threading.Event()
        received = {}

        def callback(album_id: str, success: bool) -> None:
            received["album_id"] = album_id
            received["success"] = success
            event.set()

        with patch("tide_pod.album_art.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = img_bytes
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            cache.fetch_async("album-789", "http://example.com/art.jpg", callback)
            event.wait(timeout=5.0)

        assert received["album_id"] == "album-789"
        assert received["success"] is True
        assert cache.get("album-789", width=20, height=20) is not None

    def test_fetch_async_calls_callback_on_failure(self) -> None:
        cache = AlbumArtCache(max_size=4)
        event = threading.Event()
        received = {}

        def callback(album_id: str, success: bool) -> None:
            received["album_id"] = album_id
            received["success"] = success
            event.set()

        with patch("tide_pod.album_art.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = OSError("network down")
            cache.fetch_async("album-bad", "http://example.com/fail.jpg", callback)
            event.wait(timeout=5.0)

        assert received["success"] is False
        assert cache.get("album-bad", width=10, height=10) is None


from rich.segment import Segment
from rich.style import Style

from tide_pod.album_art import AlbumArtWidget


class TestAlbumArtWidget:
    def test_render_line_blank_when_no_pixels(self) -> None:
        widget = AlbumArtWidget()
        from textual.geometry import Size
        widget._size = Size(20, 10)
        strip = widget.render_line(0)
        assert strip.cell_length == 20
        text = "".join(seg.text for seg in strip._segments)
        assert text.strip() == ""

    def test_render_line_produces_half_blocks(self) -> None:
        widget = AlbumArtWidget()
        from textual.geometry import Size
        widget._size = Size(4, 2)
        # 4 cols, 2 rows -> need pixels of shape (4, 4, 3): 2*2=4 pixel rows
        pixels = np.zeros((4, 4, 3), dtype=np.uint8)
        pixels[0, :] = [255, 0, 0]     # top row: red
        pixels[1, :] = [0, 255, 0]     # bot row: green
        pixels[2, :] = [0, 0, 255]     # top row 2: blue
        pixels[3, :] = [128, 128, 128] # bot row 2: grey
        widget.set_pixels(pixels)

        strip0 = widget.render_line(0)
        segments = list(strip0._segments)
        text = "".join(seg.text for seg in segments)
        assert "▀" in text  # upper half block

    def test_render_line_centers_narrow_image(self) -> None:
        widget = AlbumArtWidget()
        from textual.geometry import Size
        widget._size = Size(10, 2)
        # Image is only 4 cols wide, widget is 10 cols
        pixels = np.full((4, 4, 3), 200, dtype=np.uint8)
        widget.set_pixels(pixels)

        strip = widget.render_line(0)
        assert strip.cell_length == 10
        # First 3 chars should be spaces (centering: (10-4)//2 = 3)
        segments = list(strip._segments)
        leading = segments[0].text
        assert leading == "   "
