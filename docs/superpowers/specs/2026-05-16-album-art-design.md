# Album Art Display

Half-block pixel rendering of album cover art in the terminal, displayed in two locations: as a visualizer option on the Now Playing screen and as a header thumbnail on the Album screen.

## Dependencies

Add `Pillow>=10.0` to `dependencies` in `pyproject.toml`. Used for JPEG decoding and image resizing.

## New Module: `tide_pod/album_art.py`

### `AlbumArtCache`

In-memory LRU cache (max 16 entries). Stores raw PIL Image objects keyed by album ID.

**Interface:**
- `get(album_id: str, url: str, width: int, height: int) -> Optional[np.ndarray]`: returns a `(height*2, width, 3)` uint8 RGB array ready for rendering, or `None` if not yet loaded. If the album is cached but at a different size, re-renders from the cached raw image.
- `fetch_async(album_id: str, url: str, callback: Callable)`: fetches in a background thread if not already cached. Calls `callback` on completion (from the worker thread; caller marshals to UI).

**Fetch logic:**
1. `urllib.request.urlopen(url)` to read bytes
2. `PIL.Image.open(BytesIO(bytes)).convert("RGB")`
3. Store raw image in LRU
4. Resize to requested dimensions using `Image.LANCZOS`
5. Convert to numpy array

### `AlbumArtWidget(Widget)`

Textual widget that renders a pixel array as half-block characters.

**State:**
- `_pixels: Optional[np.ndarray]`: shape `(rows*2, cols, 3)`, dtype uint8. `None` means nothing to show.

**`render_line(y: int) -> Strip`:**
1. If `_pixels` is None or dimensions don't match, return `Strip.blank(width)`.
2. Compute pixel rows: `top_row = _pixels[y * 2]`, `bot_row = _pixels[y * 2 + 1]`.
3. For each column `x` in `0..width`:
   - `top_rgb = top_row[x]`
   - `bot_rgb = bot_row[x]`
   - Emit `Segment("▀", Style(color=f"rgb({r},{g},{b})", bgcolor=f"rgb({r},{g},{b})"))`
4. If image is narrower than widget, center with blank-padded segments on each side.

**`set_pixels(pixels: Optional[np.ndarray]) -> None`:**
- Updates `_pixels`, calls `self.refresh()`.

### `AlbumArtVisualizer(Visualizer)`

Subclass of `Visualizer` (from `screens/now_playing.py`) that displays album art centered in the available space.

**Behavior:**
- Overrides `FPS = 2` (only needs to detect track changes, not animate).
- On mount and on each `_tick()`, checks if the current track's album ID has changed.
- If changed, requests art from `AlbumArtCache.fetch_async()` with dimensions matching the widget size.
- On callback, calls `set_pixels()` (marshaled to UI thread via `app.call_from_thread`).
- Centers the art: if the widget is wider than the image (maintaining square aspect ratio), pads left/right with blank space.
- On resize, re-renders from cached raw image at new dimensions.
- `DISPLAY_NAME = "Album Art"`

**Registration:**
Add `("art", "Album Art", AlbumArtVisualizer)` to `VISUALIZER_OPTIONS` in `screens/now_playing.py`, between VU and Off.

## Album Screen Integration

Modify `AlbumScreen.compose()`:

**Current layout:**
```
Header
Label (album title)
Static (album meta)
DataTable (tracks)
Footer
```

**New layout:**
```
Header
Horizontal:
  AlbumArtWidget (fixed width=20, height=10)
  Vertical:
    Label (album title)
    Static (album meta)
DataTable (tracks)
Footer
```

The art widget is 20 columns wide x 10 rows tall (renders 20x20 effective pixels, recognizable at a glance).

**Fetch timing:** The existing `_load` worker already fetches album data in a thread. After loading tracks, it also fetches the album art via `AlbumArtCache` and updates the widget from `call_from_thread`.

## CSS Changes

```css
/* Album screen header art */
#album-art {
    width: 20;
    height: 10;
    margin-right: 1;
}

/* Album art visualizer centers content */
AlbumArtVisualizer {
    height: 1fr;
    content-align: center middle;
}
```

## Error Handling

- Network failure, bad URL, or decode failure: widget stays blank (no pixels set). No retry, no error notification. The UI works fine without art.
- Track has no album: widget stays blank.
- Widget resizes while art is cached: re-render from cached raw image at new dimensions on next `_tick()`.

## Image Sizing Strategy

- **Now Playing visualizer:** Art is rendered as a square, sized to `min(widget_width, widget_height * 2)` pixels on each side (since cells are roughly 2:1 aspect ratio). Centered in the widget area.
- **Album screen thumbnail:** Fixed at 20x20 pixels (20 cols x 10 rows).

## What This Does NOT Include

- Disk caching
- Kitty/iTerm2/Sixel graphics protocol support
- Placeholder/loading spinner
- Color quantization or dithering (true-color output only; terminals without 24-bit color will approximate via their palette automatically)
