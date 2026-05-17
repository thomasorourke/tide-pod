"""Bit-perfect GStreamer player.

Pipeline (audio-sink bin under playbin3):

    queue ! audioconvert ! tee name=t
      t. ! queue ! alsasink device=hw:X,Y
      t. ! queue leaky=downstream max-size-buffers=2 ! audioconvert
              ! audio/x-raw,format=F32LE,channels=2
              ! appsink name=visapp emit-signals=true sync=false drop=true max-buffers=1

Notes on bit-perfect:
    * No `audioresample` — `audioconvert` only handles format/layout (e.g.
      sample format / channel layout / interleaving), never sample rate.
    * `alsasink` is opened on a `hw:` device so the kernel does not run a
      mixer or rate converter.
    * If a new track has a different sample rate than the previous one, the
      pipeline is briefly set to NULL so `alsasink` re-negotiates the rate
      from scratch and re-opens the device.
    * The visualizer lives on a parallel tee branch terminating in an
      `appsink`. The ALSA branch does not see any extra processing, and
      `leaky=downstream` + `drop=true` means the analyzer can never apply
      back-pressure to the ALSA branch.

Visualizer analyzer (custom — replaces GStreamer's `spectrum` element):
    * `appsink` pushes F32LE stereo PCM buffers to Python.
    * Two parallel ring buffers (L/R) keep ~4 s of audio.
    * A worker thread runs a 2048-sample Hann-windowed FFT plus per-channel
      RMS at ~90 Hz against the most recent audio, exposed via
      `spectrum_snapshot()` and `vu_snapshot()`.
    * The FFT window is read from `write_head − vis_offset` samples back in
      the ring buffer, so the analyzer shows what's coming out the DAC
      rather than what's queued ahead in alsasink's prebuffer.

The GLib mainloop runs in a daemon thread so the rest of the app (Textual,
asyncio) can stay on the main thread. Callbacks the UI subscribes to are
invoked from that thread; the UI is responsible for marshaling onto its
own loop.
"""

from __future__ import annotations

import base64
import logging
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

import gi
import numpy as np

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
from gi.repository import GLib, Gst, GstApp  # noqa: E402

from tidalapi.media import ManifestMimeType, Track  # noqa: E402

logger = logging.getLogger(__name__)


@dataclass
class NowPlaying:
    track: Optional[Track] = None
    position_ns: int = 0
    duration_ns: int = 0
    playing: bool = False
    # What ALSA negotiated and is actually pushing out (from the sink's caps)
    sample_rate: int = 0  # Hz, 0 if unknown
    bit_depth: int = 0  # 0 if unknown
    channels: int = 0
    # What Tidal sent us (the source side)
    source_sample_rate: int = 0
    source_bit_depth: int = 0
    source_quality: str = ""  # LOW, HIGH, LOSSLESS, HI_RES_LOSSLESS
    source_mode: str = ""  # STEREO, DOLBY_ATMOS, etc.
    alsa_device: str = ""


class Player:
    """A small GStreamer-based player.

    Public API used by the TUI:
        play_track(track)
        play_tracks(tracks, start_index=0)
        toggle()
        next() / previous()
        seek_fraction(0..1)
        snapshot() -> NowPlaying

    Callbacks (called from the GLib thread):
        on_state_changed(NowPlaying)
        on_track_changed(NowPlaying)
        on_error(str)
    """

    # FFT size is the dominant factor in jitter: tiny windows give noisy
    # bin values that jump frame to frame. 2048 samples (~43 ms @ 48 kHz)
    # gives stable bins; the widget's EMA smoothing handles snappy motion.
    SPECTRUM_FFT_SIZE = 2048
    SPECTRUM_BANDS = SPECTRUM_FFT_SIZE // 2
    SPECTRUM_HOP_HZ = 90  # ~11 ms data refresh — fresher than render frames
    SPECTRUM_FLOOR_DB = -80.0
    SPECTRUM_CEIL_DB = -10.0

    # VU dynamics: peak holds, then decays. A bigger RMS window keeps the
    # bar value stable (less jitter); the widget's attack/release smoothing
    # handles perceptual responsiveness.
    VU_PEAK_DECAY = 0.12  # per FFT hop → reaches 0 in ~140 ms
    VU_RMS_WINDOW = 2048  # ~43 ms at 48 kHz — stable, low jitter
    # VU dB scale — tighter than the FFT-bin scale. Modern music sits around
    # -15..-25 dBFS RMS, peaks at -3..-10 dBFS, so this range gives
    # meaningful motion in the middle of the meter.
    VU_FLOOR_DB = -50.0
    VU_CEIL_DB = -3.0

    def __init__(
        self,
        alsa_device: str,
        vis_offset_ms: int = 300,
        backend: str = "alsa",
    ) -> None:
        Gst.init(None)
        # "alsa": exclusive hw: device, bit-perfect. "pulse": pulsesink, shared.
        self.backend = backend
        # Output identifier shown in the UI. Kept under the historical
        # `alsa_device` name to avoid churning the snapshot schema.
        self.alsa_device = "PulseAudio (shared)" if backend == "pulse" else alsa_device
        # User-tunable offset from the freshest decoded audio backward to
        # "what's currently playing." Tune with [ and ] in the Now Playing
        # view. Stored in milliseconds; converted to samples on use.
        self.vis_offset_ms: int = vis_offset_ms

        # Analyzer state. Stereo audio is kept in two parallel ring buffers
        # so a) the FFT can downmix on demand, and b) VU meters get
        # per-channel data without re-extracting from the stream.
        self._spectrum_lock = threading.Lock()
        self._spectrum_magnitudes: List[float] = [0.0] * self.SPECTRUM_BANDS
        self._spectrum_rate: int = 0
        # Per-channel VU metrics (0..1, post normalization)
        self._vu_left_rms: float = 0.0
        self._vu_right_rms: float = 0.0
        self._vu_left_peak: float = 0.0
        self._vu_right_peak: float = 0.0
        # How many samples behind the write head to analyze, so the bars
        # show what's audible RIGHT NOW (not the decoded-ahead audio).
        # Updated from `vis_offset_ms` whenever a new appsink buffer arrives.
        self._audio_latency_samples: int = 0
        # Larger ring buffer so we can OFFSET reads backward by the pipeline's
        # audio latency (alsasink prebuffer, ~200-500 ms) and analyze the
        # audio that's actually playing right now, not what's queued ahead.
        ring_size = max(self.SPECTRUM_FFT_SIZE * 4, 192_000)  # ≥ ~4 s @ 48k
        self._ring_l = np.zeros(ring_size, dtype=np.float32)
        self._ring_r = np.zeros(ring_size, dtype=np.float32)
        self._ring_lock = threading.Lock()
        self._ring_write = 0  # next slot to write
        self._ring_filled = 0  # how many samples have been written total
        self._hann = np.hanning(self.SPECTRUM_FFT_SIZE).astype(np.float32)
        self._fft_stop = threading.Event()
        self._fft_thread = threading.Thread(
            target=self._fft_loop, name="tide-pod-fft", daemon=True
        )

        self.pipeline: Gst.Pipeline = Gst.Pipeline.new("tide-pod")
        self.playbin: Gst.Element = Gst.ElementFactory.make("playbin3", "playbin")
        if self.playbin is None:
            self.playbin = Gst.ElementFactory.make("playbin", "playbin")
        if self.playbin is None:
            raise RuntimeError("Could not create a GStreamer playbin element")
        self.pipeline.add(self.playbin)

        self._install_sink()

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", self._on_eos)
        bus.connect("message::error", self._on_error)
        bus.connect("message::state-changed", self._on_state_changed)
        bus.connect("message::stream-start", self._on_stream_start)

        # Queue state
        self._queue: List[Track] = []
        self._history: List[Track] = []
        self._current: Optional[Track] = None
        self._current_rate: int = 0
        self._current_depth: int = 0
        self._current_channels: int = 0
        self._source_rate: int = 0
        self._source_depth: int = 0
        self._source_quality: str = ""
        self._source_mode: str = ""
        # User intent tracker for play/pause. We can't read the actual
        # pipeline state with a zero timeout reliably — transitions are
        # async, so a fast space-space press could race the previous
        # PAUSED transition. The intent flag is the source of truth.
        self._intended_state: Gst.State = Gst.State.NULL
        # Last known position when the user paused. Used to re-seek on
        # resume; see toggle() for why.
        self._paused_position_ns: int = 0
        self._lock = threading.Lock()

        # UI callbacks (set by app)
        self.on_state_changed: Optional[Callable[[NowPlaying], None]] = None
        self.on_track_changed: Optional[Callable[[NowPlaying], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

        # MPD manifests are written here so adaptivedemux2 can read them
        # off the local filesystem (it's much friendlier than data: URIs).
        self._manifest_path = Path(GLib.get_user_cache_dir()) / "tide-pod" / "manifest.mpd"
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)

        # GLib mainloop on a daemon thread
        self._mainloop = GLib.MainLoop()
        self._mainloop_thread = threading.Thread(
            target=self._mainloop.run, name="gst-mainloop", daemon=True
        )
        self._mainloop_thread.start()

    # ------------------------------------------------------------------
    # Pipeline setup
    # ------------------------------------------------------------------
    def _install_sink(self) -> None:
        """Build the audio sink bin and attach it to playbin.

        ALSA mode: exclusive hw: device, bit-perfect.
        Pulse mode: pulsesink — shared via PulseAudio/PipeWire so other apps
        keep working at the same time. Pulse manages its own resampling, so
        bit-perfect is off the table here.

        Spectrum branch is a leaky tee tap into an appsink; the FFT runs in
        Python so we get a snappy, accurate analyzer with no impact on the
        output branch.
        """
        if self.backend == "pulse":
            output = "pulsesink"
        else:
            output = f"alsasink device={self.alsa_device}"
        desc = (
            f"queue ! audioconvert ! tee name=t "
            f"t. ! queue ! {output} "
            # sync=false: the appsink pulls buffers as fast as possible so the
            # FFT thread always has fresh data, instead of being clock-gated
            # to the audio buffer arrival rate. Combined with drop=true and
            # max-buffers=1, the analyzer is pinned to the latest decoded
            # audio. (The visualizer leads what you hear by the sink's
            # prebuffer, but the bars respond at a high frame rate.)
            f"t. ! queue leaky=downstream max-size-buffers=2 max-size-time=0 max-size-bytes=0 "
            f"! audioconvert ! audio/x-raw,format=F32LE,channels=2 ! "
            f"appsink name=visapp emit-signals=true sync=false drop=true max-buffers=1"
        )
        bin_ = Gst.parse_bin_from_description(desc, True)
        if bin_ is None:
            raise RuntimeError(f"Could not build audio sink pipeline: {desc}")
        self.playbin.set_property("audio-sink", bin_)

        appsink = bin_.get_by_name("visapp")
        if appsink is not None:
            appsink.connect("new-sample", self._on_appsink_sample)
        if not self._fft_thread.is_alive():
            self._fft_thread.start()

    def set_alsa_device(self, device: str) -> None:
        """Switch ALSA device. Stops playback; caller must restart."""
        self.pipeline.set_state(Gst.State.NULL)
        self.alsa_device = device
        self._install_sink()

    # ------------------------------------------------------------------
    # Public playback API
    # ------------------------------------------------------------------
    def play_track(self, track: Track) -> None:
        with self._lock:
            self._queue = []
            self._history = []
        self._start(track, gapless=False)

    def play_tracks(self, tracks: List[Track], start_index: int = 0) -> None:
        if not tracks:
            return
        start_index = max(0, min(start_index, len(tracks) - 1))
        with self._lock:
            self._queue = list(tracks[start_index + 1 :])
            self._history = list(tracks[:start_index])
        self._start(tracks[start_index], gapless=False)

    def toggle(self) -> None:
        """Flip play / pause based on the user's tracked intent."""
        try:
            if self._intended_state == Gst.State.PLAYING:
                # Remember where we are so resume can re-seek the pipeline.
                self._paused_position_ns = self._query_position_ns()
                self._intended_state = Gst.State.PAUSED
                self.pipeline.set_state(Gst.State.PAUSED)
            else:
                if not self.playbin.get_property("uri"):
                    return
                self._intended_state = Gst.State.PLAYING
                self.pipeline.set_state(Gst.State.PLAYING)
                # Bit-perfect hw:* alsasinks frequently come out of
                # PAUSED → PLAYING with the device still stalled: state
                # transitions cleanly (UI flips to ▶) but no audio flows.
                # A flushing seek to the paused position re-primes the
                # sink so it actually starts producing samples again.
                if self._paused_position_ns > 0:
                    self.pipeline.seek_simple(
                        Gst.Format.TIME,
                        Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                        self._paused_position_ns,
                    )
            # Don't fire _emit_state() here: the pipeline's state-changed bus
            # message will trigger _on_state_changed on the GLib thread, which
            # is the right place to update the UI from.
        except Exception:
            logger.exception("toggle failed")

    def next(self) -> bool:
        """Skip to the next track. Returns False if nothing queued."""
        with self._lock:
            if not self._queue:
                return False
            track = self._queue.pop(0)
            if self._current is not None:
                self._history.append(self._current)
        self._start(track, gapless=False)
        return True

    def previous(self) -> bool:
        """Restart the current track if >2s in, else jump to the previous.

        Returns False only when we'd otherwise do nothing (no history and
        we're already near the start of the track).
        """
        pos = self._query_position_ns()
        if pos > 2 * Gst.SECOND:
            self.pipeline.seek_simple(
                Gst.Format.TIME, Gst.SeekFlags.FLUSH, 0
            )
            return True
        with self._lock:
            if not self._history:
                return False
            track = self._history.pop()
            if self._current is not None:
                self._queue.insert(0, self._current)
        self._start(track, gapless=False)
        return True

    def seek_fraction(self, fraction: float) -> None:
        fraction = max(0.0, min(1.0, fraction))
        dur = self._query_duration_ns()
        if dur <= 0:
            return
        self.pipeline.seek_simple(
            Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, int(dur * fraction)
        )

    def snapshot(self) -> NowPlaying:
        _ret, state, _pending = self.pipeline.get_state(0)
        return NowPlaying(
            track=self._current,
            position_ns=self._query_position_ns(),
            duration_ns=self._query_duration_ns(),
            playing=state == Gst.State.PLAYING,
            sample_rate=self._current_rate,
            bit_depth=self._current_depth,
            channels=self._current_channels,
            source_sample_rate=self._source_rate,
            source_bit_depth=self._source_depth,
            source_quality=self._source_quality,
            source_mode=self._source_mode,
            alsa_device=self.alsa_device,
        )

    def shutdown(self) -> None:
        self._fft_stop.set()
        self.pipeline.set_state(Gst.State.NULL)
        if self._mainloop.is_running():
            self._mainloop.quit()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _start(self, track: Track, gapless: bool) -> None:
        """Load the track's manifest off the main loop, then set the URI."""
        threading.Thread(
            target=self._load_and_play, args=(track, gapless), daemon=True
        ).start()

    def _load_and_play(self, track: Track, gapless: bool) -> None:
        try:
            stream = track.get_stream()
            manifest = stream.get_stream_manifest()
            # Capture source-side info before we go further.
            with self._lock:
                self._source_rate = int(getattr(stream, "sample_rate", 0) or 0)
                self._source_depth = int(getattr(stream, "bit_depth", 0) or 0)
                self._source_quality = str(getattr(stream, "audio_quality", "") or "")
                self._source_mode = str(getattr(stream, "audio_mode", "") or "")
            if stream.manifest_mime_type == ManifestMimeType.MPD:
                data = stream.get_manifest_data()
                if not data:
                    raise RuntimeError("Empty MPD manifest")
                major, minor, *_ = Gst.version()
                if (major, minor) >= (1, 26):
                    self._manifest_path.write_text(
                        data if isinstance(data, str) else data.decode("utf-8"),
                        encoding="utf-8",
                    )
                    uri = f"file://{self._manifest_path}"
                else:
                    raw = data.encode("utf-8") if isinstance(data, str) else data
                    uri = "data:application/dash+xml;base64," + base64.b64encode(raw).decode("ascii")
            elif stream.manifest_mime_type == ManifestMimeType.BTS:
                urls = manifest.get_urls()
                uri = urls[0] if isinstance(urls, list) else urls
            else:
                raise RuntimeError(f"Unsupported manifest type: {stream.manifest_mime_type}")
        except Exception as exc:
            logger.exception("Failed to load stream for %s", track)
            self._call_error(f"Failed to load track: {exc}")
            return

        GLib.idle_add(self._apply_uri, track, uri, gapless)

    def _apply_uri(self, track: Track, uri: str, gapless: bool) -> bool:
        # Reset pipeline so alsasink renegotiates if the new track has a
        # different sample rate. Cheap and reliable; bit-perfect demands it.
        self.pipeline.set_state(Gst.State.NULL)
        self.playbin.set_property("uri", uri)
        with self._lock:
            self._current = track
            self._current_rate = 0
            self._current_depth = 0
            self._current_channels = 0
        self._intended_state = Gst.State.PLAYING
        self.pipeline.set_state(Gst.State.PLAYING)
        self._call_track_changed()
        return False  # one-shot idle

    def _on_eos(self, _bus: Gst.Bus, _msg: Gst.Message) -> None:
        with self._lock:
            has_next = bool(self._queue)
        if has_next:
            GLib.idle_add(lambda: (self.next(), False)[1])
        else:
            self._intended_state = Gst.State.PAUSED
            self.pipeline.set_state(Gst.State.PAUSED)
            self._emit_state()

    def _on_error(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        err, debug = message.parse_error()
        logger.error("GStreamer error: %s | %s", err.message, debug)
        self._call_error(err.message)

    def _on_state_changed(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        if message.src is not self.pipeline:
            return
        _old, new, _pending = message.parse_state_changed()
        # Caps aren't negotiated at stream-start; they are by PLAYING.
        if new == Gst.State.PLAYING:
            self._capture_alsa_caps()
        self._emit_state()

    def _on_stream_start(self, _bus: Gst.Bus, _message: Gst.Message) -> None:
        # Try once here too — sometimes caps are ready by stream-start, and
        # capturing earlier means the UI updates sooner.
        self._capture_alsa_caps()

    def _on_appsink_sample(self, appsink: GstApp.AppSink) -> Gst.FlowReturn:
        """Pull a sample, deinterleave L/R, append to ring buffers.

        Wrapped so a Python exception here can't poison the GStreamer
        pipeline; we always return a FlowReturn even on failure.
        """
        try:
            sample = appsink.emit("pull-sample")
            if sample is None:
                return Gst.FlowReturn.OK
            caps = sample.get_caps()
            rate = 0
            if caps is not None and caps.get_size():
                s = caps.get_structure(0)
                ok, r = s.get_int("rate")
                if ok:
                    rate = r
                    with self._spectrum_lock:
                        self._spectrum_rate = rate
            buf = sample.get_buffer()
            ok, mapinfo = buf.map(Gst.MapFlags.READ)
            if not ok:
                return Gst.FlowReturn.OK
            try:
                data = np.frombuffer(mapinfo.data, dtype=np.float32)
                if data.size == 0:
                    return Gst.FlowReturn.OK
                frames = data.reshape(-1, 2)
                left = frames[:, 0].copy()
                right = frames[:, 1].copy()
            finally:
                buf.unmap(mapinfo)

            n = left.shape[0]
            with self._ring_lock:
                size = self._ring_l.shape[0]
                w = self._ring_write
                if n >= size:
                    self._ring_l[:] = left[-size:]
                    self._ring_r[:] = right[-size:]
                    self._ring_write = 0
                else:
                    end = w + n
                    if end <= size:
                        self._ring_l[w:end] = left
                        self._ring_r[w:end] = right
                    else:
                        first = size - w
                        self._ring_l[w:] = left[:first]
                        self._ring_l[: n - first] = left[first:]
                        self._ring_r[w:] = right[:first]
                        self._ring_r[: n - first] = right[first:]
                    self._ring_write = end % size
                self._ring_filled = min(self._ring_filled + n, size)

            if rate:
                lat_samples = max(0, int(self.vis_offset_ms * rate / 1000))
                lat_samples = min(lat_samples, rate)
                with self._ring_lock:
                    self._audio_latency_samples = lat_samples
        except Exception:
            logger.exception("appsink sample handling failed")
        return Gst.FlowReturn.OK

    def _fft_loop(self) -> None:
        """Worker thread: ~90 Hz analysis against the freshest samples.

        The analysis window is offset backward in the ring buffer by the
        pipeline's audio latency so the visuals match what's coming out the
        DAC right now.
        """
        period = 1.0 / self.SPECTRUM_HOP_HZ
        N = self.SPECTRUM_FFT_SIZE
        floor = self.SPECTRUM_FLOOR_DB
        ceil = self.SPECTRUM_CEIL_DB
        denom = ceil - floor
        vu_n = self.VU_RMS_WINDOW
        vu_floor = self.VU_FLOOR_DB
        vu_denom = self.VU_CEIL_DB - self.VU_FLOOR_DB

        def to01_vu(v: float) -> float:
            return min(1.0, max(0.0, (20.0 * math.log10(v + 1e-12) - vu_floor) / vu_denom))

        while not self._fft_stop.is_set():
            start = time.monotonic()
            left, right = self._latest_stereo(max(N, vu_n))
            if left is not None and right is not None:
                # --- Spectrum (mono downmix, last N samples) ---
                mono = (left[-N:] + right[-N:]) * 0.5
                spec = np.fft.rfft(mono * self._hann)
                mag = np.abs(spec[1 : N // 2 + 1])
                mag *= 2.0 / (self._hann.sum() or 1.0)
                db = 20.0 * np.log10(mag + 1e-12)
                norm = np.clip((db - floor) / denom, 0.0, 1.0)
                values = norm.astype(np.float64).tolist()

                # --- VU (RMS + sample peak per channel, last vu_n samples) ---
                lw = left[-vu_n:]
                rw = right[-vu_n:]
                l_rms = float(np.sqrt(np.mean(lw * lw) + 1e-12))
                r_rms = float(np.sqrt(np.mean(rw * rw) + 1e-12))
                l_pk = float(np.max(np.abs(lw)))
                r_pk = float(np.max(np.abs(rw)))
                l_rms_n = to01_vu(l_rms)
                r_rms_n = to01_vu(r_rms)
                l_pk_n = to01_vu(l_pk)
                r_pk_n = to01_vu(r_pk)

                with self._spectrum_lock:
                    self._spectrum_magnitudes = values
                    self._vu_left_rms = l_rms_n
                    self._vu_right_rms = r_rms_n
                    # Peak hold/decay (rises instantly, decays slowly).
                    self._vu_left_peak = max(l_pk_n, self._vu_left_peak - self.VU_PEAK_DECAY)
                    self._vu_right_peak = max(r_pk_n, self._vu_right_peak - self.VU_PEAK_DECAY)
            else:
                with self._spectrum_lock:
                    self._spectrum_magnitudes = [0.0] * self.SPECTRUM_BANDS
                    self._vu_left_rms = 0.0
                    self._vu_right_rms = 0.0
                    self._vu_left_peak = max(0.0, self._vu_left_peak - self.VU_PEAK_DECAY)
                    self._vu_right_peak = max(0.0, self._vu_right_peak - self.VU_PEAK_DECAY)

            elapsed = time.monotonic() - start
            sleep = period - elapsed
            if sleep > 0:
                self._fft_stop.wait(sleep)

    def set_vis_offset_ms(self, ms: int) -> None:
        """Tune the visualizer offset (how far back from latest audio to read).
        Bigger = bars happen later (toward what you hear); smaller = earlier."""
        self.vis_offset_ms = max(0, min(1000, int(ms)))

    def _latest_stereo(self, n: int):
        """Pull `n` samples per channel from the ring buffer, contiguous.

        The window ends at (write_head - audio_latency_samples), so the
        analyzed audio is what's currently coming out the DAC, not what's
        been decoded ahead of time.
        """
        with self._ring_lock:
            size = self._ring_l.shape[0]
            offset = self._audio_latency_samples
            need = n + offset
            if self._ring_filled < need:
                return None, None
            end = (self._ring_write - offset) % size
            start = (end - n) % size
            if start < end:
                return self._ring_l[start:end].copy(), self._ring_r[start:end].copy()
            else:
                return (
                    np.concatenate((self._ring_l[start:], self._ring_l[:end])),
                    np.concatenate((self._ring_r[start:], self._ring_r[:end])),
                )

    def spectrum_snapshot(self) -> List[float]:
        """Return the latest spectrum magnitudes, one float in 0..1 per band."""
        with self._spectrum_lock:
            return list(self._spectrum_magnitudes)

    def spectrum_sample_rate(self) -> int:
        """Sample rate of the audio feeding the analyzer (Hz). 0 if unknown."""
        with self._spectrum_lock:
            return self._spectrum_rate

    def vu_snapshot(self):
        """Return (left_rms, left_peak, right_rms, right_peak), each in 0..1."""
        with self._spectrum_lock:
            return (
                self._vu_left_rms,
                self._vu_left_peak,
                self._vu_right_rms,
                self._vu_right_peak,
            )

    def _capture_alsa_caps(self) -> None:
        sink = self.playbin.get_property("audio-sink")
        if sink is None:
            return
        target_factory = "pulsesink" if self.backend == "pulse" else "alsasink"
        output_sink = None
        if hasattr(sink, "iterate_elements"):
            it = sink.iterate_elements()
            while True:
                ok, element = it.next()
                if ok != Gst.IteratorResult.OK:
                    break
                factory = element.get_factory()
                if factory and factory.get_name() == target_factory:
                    output_sink = element
                    break
        if output_sink is None:
            return
        pad = output_sink.get_static_pad("sink")
        if pad is None:
            return
        caps = pad.get_current_caps()
        if caps is None or caps.get_size() == 0:
            return
        s = caps.get_structure(0)
        ok_rate, rate = s.get_int("rate")
        ok_ch, channels = s.get_int("channels")
        fmt = s.get_string("format") or ""
        # GStreamer audio formats look like S16LE, S24_32LE, F32LE, etc.
        depth = 0
        for token in (fmt.replace("LE", "").replace("BE", "").replace("U", "").replace("F", "").replace("S", "").split("_")):
            try:
                depth = int(token)
                break
            except ValueError:
                continue
        with self._lock:
            self._current_rate = rate if ok_rate else 0
            self._current_depth = depth
            self._current_channels = channels if ok_ch else 0
        self._call_track_changed()

    def _query_position_ns(self) -> int:
        ok, pos = self.pipeline.query_position(Gst.Format.TIME)
        return pos if ok else 0

    def _query_duration_ns(self) -> int:
        ok, dur = self.pipeline.query_duration(Gst.Format.TIME)
        return dur if ok else 0

    # ---- callback dispatch -------------------------------------------------
    def _emit_state(self) -> None:
        if self.on_state_changed:
            try:
                self.on_state_changed(self.snapshot())
            except Exception:
                logger.exception("on_state_changed callback failed")

    def _call_track_changed(self) -> None:
        if self.on_track_changed:
            try:
                self.on_track_changed(self.snapshot())
            except Exception:
                logger.exception("on_track_changed callback failed")

    def _call_error(self, msg: str) -> None:
        if self.on_error:
            try:
                self.on_error(msg)
            except Exception:
                logger.exception("on_error callback failed")
