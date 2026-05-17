# tide-pod

> Delicious audio.

A terminal Tidal client. Defaults to PulseAudio/PipeWire so other apps keep
working; switch to an exclusive `hw:` device for bit-perfect output.

## Features

- PKCE login (required for Lossless / Hi-Res Lossless on the latest Tidal API)
- Search across albums, tracks, artists, playlists
- Album browser with track-level playback
- Two audio backends, switchable at runtime (`ctrl+d`):
  - **PulseAudio (default)** — shared output via PipeWire/Pulse
  - **ALSA `hw:` direct** — exclusive, bit-perfect, no resampling or kernel mixing
- ALSA devices are pinned by **card name**, not `hw:CARD,DEV`, so the right
  device is picked up even when USB enumeration shuffles indices
- Now Playing screen with two visualizers (Spectrum, VU meters) + Off mode
- Real-time format display: source (FLAC 24/96 etc.) vs. output, with a
  green `BIT-PERFECT` / yellow `CONVERTED` badge
- Auto-resume on launch: the footer shows the last album/song so `space` or
  `r` picks up where you left off
- Per-user-tunable A/V sync offset for the visualizer

## Requirements

- Python 3.11+
- System GStreamer 1.26+ and `PyGObject` (1.26+ enables MPD playback for hi-res FLAC)
- ALSA (`aplay` is used to enumerate devices)
- A Tidal Hi-Fi or Hi-Fi Plus subscription (for FLAC / hi-res)

## Install

```sh
python -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
.venv/bin/tide-pod
```

`requirements.txt` pins every dependency to the exact version it was developed
against. `pyproject.toml` pins the two direct deps for installs that skip the
requirements file.

The `--system-site-packages` flag lets the venv see the system `gi`/GStreamer
bindings, which are not on PyPI.

## First run

1. **Sign in via PKCE.** tide-pod shows a Tidal login URL. Open it in your
   browser, sign in. Tidal redirects you to a tidal.com "Oops" page — copy
   that URL from the address bar and paste it back into tide-pod.
2. **Audio output.** New configs default to PulseAudio, so you should hear
   sound immediately. To go bit-perfect, press `ctrl+d` and pick a `hw:` row
   for your DAC; tide-pod will remember that card by name across reboots.

Config lives at `~/.config/tide-pod/`:

| File           | Purpose                                              |
|----------------|------------------------------------------------------|
| `config.toml`  | Audio backend, ALSA card name, quality, visualizer, A/V offset |
| `session.json` | Tidal OAuth tokens (chmod 600)                       |
| `state.json`   | Last-played item (used to show the resume hint)      |

## Keybindings

### Main screen
| Key       | Action                                |
|-----------|---------------------------------------|
| `/`       | Focus the search box                  |
| `enter`   | Open album / play row                 |
| `f`       | Open full-screen Now Playing          |
| `r`       | Resume last played item               |
| `space`   | Play / pause (or resume the remembered item if nothing is loaded) |
| `n` / `b` | Next / previous track                 |
| `ctrl+d`  | Change audio output (Pulse / hw:…)    |
| `ctrl+l`  | Logout                                |
| `q`       | Quit                                  |

### Now Playing screen
| Key       | Action                       |
|-----------|------------------------------|
| `v`       | Cycle visualizer (Spectrum → VU → Off) |
| `[` / `]` | A/V sync offset −25 / +25 ms |
| `space`   | Play / pause                 |
| `n` / `b` | Next / previous              |
| `esc`     | Back to search               |

## Bit-perfect notes

The GStreamer audio-sink is a tee. In ALSA mode the output element is
`alsasink device=hw:X,Y`; in PulseAudio mode it's `pulsesink`:

```
playbin3 → queue → audioconvert → tee
   ├── queue → alsasink / pulsesink                        (audio you hear)
   └── queue (leaky) → audioconvert → F32LE/stereo
       → appsink  (visualizer FFT analysis)
```

There is no `audioresample`. `audioconvert` only handles format/layout (not
sample rate). If a new track has a different sample rate than the previous one,
the pipeline is reset to `NULL` so the sink can re-open at the new rate. With
an exclusive `hw:` device, the kernel does not mix or resample, so the source
bit depth and rate make it to the DAC unchanged. PulseAudio mode goes through
Pulse/PipeWire's own resampler, so the `CONVERTED` badge is the norm there.

`audio_quality` defaults to `Quality.hi_res_lossless`, and PKCE auth ensures
tidalapi requests the highest stream the account is entitled to.

The visualizer branch is `leaky=downstream` + `drop=true` + `max-buffers=1` so
it can never apply back-pressure to the ALSA branch. The analyzer runs a
2048-sample Hann-windowed FFT at ~90 Hz in a Python worker thread.

## Tests

```sh
.venv/bin/pip install pytest
.venv/bin/pytest
```

Tests cover the deterministic pieces — config / state round-trip, `aplay`
parsing, FFT correctness against synthetic tones, spectrum / VU widget
helpers. The Tidal API and GStreamer pipeline are not exercised in CI.

## License

GPL-3.0-or-later. See `LICENSE`.
