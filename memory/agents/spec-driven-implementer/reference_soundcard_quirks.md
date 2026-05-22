---
name: reference-soundcard-quirks
description: soundcard (libpulse / WASAPI) library quirks that bite when migrating from sounddevice or writing fakes
metadata:
  type: reference
---

`soundcard` (PyPI, currently 0.4.6) is the PulseAudio / WASAPI backend the
mic modality runs on. Things that bit during the Phase 1 migration from
sounddevice and may bite again:

- **Import-time argv probe crashes on empty argv.** `soundcard/pulseaudio.py`
  reads `sys.argv[1]` to set the libpulse client name. A bare
  `uv run python -c "import soundcard"` fails with `IndexError: list index out of range`. Smoke checks must set `sys.argv = ["x", "dummy"]` (or run
  via a `-m` entry point that has a real argv) before importing.
- **No public `Speaker` / `Microphone` type to import.** The module
  surfaces `_Speaker` / `_Microphone` from `soundcard.pulseaudio`; nothing
  is re-exported as a typed name. Production code should accept the duck-
  typed handle via `Any` and read `id` / `name` / `channels` /
  `player(...)` / `recorder(...)` defensively.
- **`speaker.player(samplerate, channels=None, blocksize=None)` returns a
  context manager**, not a stream. Mic owns `self._player_cm` and calls
  `self._player_cm.__enter__()` / `.__exit__(None, None, None)` manually
  so the existing `Mic.close()` lifecycle stays intact.
- **`get_speaker(name)` raises `LookupError` on miss** (case-insensitive
  substring on `name` + fuzzy id match -- internal ordering among
  multiple matches is implementation-defined, do not assert
  "first match wins" in tests). `lookup_speaker` in
  `src/vrcpilot/mic/devices.py` delegates to `sc.get_speaker(name)` and
  catches `LookupError` only (the public contract); on miss it
  enumerates `all_speakers()` to produce the listing-style
  `MicDeviceNotFoundError` message. The earlier defensive
  `IndexError` catch was removed because no reproducer was ever
  documented and `IndexError` from soundcard internals would now signal
  a real upstream bug rather than be silently swallowed.
- **Native errors surface as `RuntimeError`** (libpulse) or `OSError`
  (missing shared library). `Mic` lets these propagate.
- **`Speaker.id`** is the PulseAudio sink name on Linux (e.g.
  `"VRCPilotMic"`) and the WASAPI device id on Windows. `Mic.device_id`
  exposes it directly.

Fake side: `tests/fakes/audio.py` ships `FakeSoundCard` /
`FakeSoundCardSpeaker` / `FakeSoundCardPlayer{,CM}` /
`FakeSoundCardMicrophone` / `FakeSoundCardRecorder{,CM}`. Install via
`mocker.patch.dict(sys.modules, {"soundcard": FakeSoundCard()})`. The
mic-side `FakeSpeaker` name was deliberately kept as the **speaker
modality** fake (mirrors `vrcpilot.speaker.session.Speaker`); the
soundcard-side fakes carry the `FakeSoundCard` prefix to avoid the
collision.
