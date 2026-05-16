# tide-pod

> Delicious audio.

A terminal Tidal client with bit-perfect ALSA output.

## Features

- PKCE login (required for Lossless / Hi-Res Lossless on the latest Tidal API)
- Search across albums, tracks, artists, playlists
- Album browser with track-level playback
- Bit-perfect ALSA output to a `hw:` device — no resampling, no kernel mixing
- Now Playing screen with two visualizers (Spectrum, VU meters) + an Off mode
- Real-time format display: source (FLAC 24/96 etc.) vs. ALSA output, with a
  green `BIT-PERFECT` / yellow `CONVERTED` badge
- Resume last played album / track / artist / playlist with one keypress
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
2. **Pick an ALSA device.** Choose a `hw:CARD,DEV` entry for true bit-perfect
   output. The default ALSA device routes through PulseAudio/PipeWire and
   is *not* bit-perfect.

Config lives at `~/.config/tide-pod/`:

| File           | Purpose                                |
|----------------|----------------------------------------|
| `config.toml`  | ALSA device, quality, visualizer, A/V offset |
| `session.json` | Tidal OAuth tokens (chmod 600)        |
| `state.json`   | Last-played item (for `r` resume)     |

## Keybindings

### Main screen
| Key       | Action                       |
|-----------|------------------------------|
| `/`       | Focus the search box         |
| `enter`   | Open album / play row        |
| `f`       | Open full-screen Now Playing |
| `r`       | Resume last played item      |
| `space`   | Play / pause                 |
| `n` / `b` | Next / previous track        |
| `ctrl+l`  | Logout                       |
| `q`       | Quit                         |

### Now Playing screen
| Key       | Action                       |
|-----------|------------------------------|
| `v`       | Cycle visualizer (Spectrum → VU → Off) |
| `[` / `]` | A/V sync offset −25 / +25 ms |
| `space`   | Play / pause                 |
| `n` / `b` | Next / previous              |
| `esc`     | Back to search               |

## Bit-perfect notes

The GStreamer audio-sink is a tee:

```
playbin3 → queue → audioconvert → tee
   ├── queue → alsasink device=hw:X,Y                      (audio you hear)
   └── queue (leaky) → audioconvert → F32LE/stereo
       → appsink  (visualizer FFT analysis)
```

There is no `audioresample`. `audioconvert` only handles format/layout (not
sample rate). If a new track has a different sample rate than the previous one,
the pipeline is reset to `NULL` so `alsasink` can re-open the device at the new
rate. With an exclusive `hw:` device, the kernel does not mix or resample.

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
