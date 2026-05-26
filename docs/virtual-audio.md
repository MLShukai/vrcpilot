# Virtual Audio Guide

**English** | [日本語](virtual-audio.ja.md)

How to fan VRChat's output audio out to different devices per PID. This page covers `vrcpilot speaker`, how it composes with third-party helpers, and how to tune latency. For the flag-level CLI reference see [`cli.md`](cli.md); for the equivalent Python API see [`python-api.md`](python-api.md).

______________________________________________________________________

## Overview

The problem this feature solves: when you run multiple VRChat instances at once (multi-instance), you want each PID's audio to land on a different physical or virtual speaker. OS-level per-application output routing (Windows' `IAudioPolicyConfig`, EarTrumpet) ultimately resolves apps by their **exe-path-based AppIdentity**, so there is no API-level guarantee that two instances of the same `VRChat.exe` can be split per PID. On top of that, VRChat spawns the real process through `start_protected_game.exe`, which makes those policy-registration APIs prone to soft-failing.

vrcpilot already has **per-PID audio capture** (Windows: proc-tap, Linux: PipeWire native, both 48 kHz / stereo / float32). Relaying that into an arbitrary output device through `soundcard` in user space yields per-PID separation without depending on any OS policy, and without modifying the client (which would be an EAC violation).

______________________________________________________________________

## How it works

```
VRChat (PID=N) ──[proc-tap / PipeWire capture]──> vrcpilot.Speaker
                                                         │
                                                         ▼
                                          soundcard.Player (any output device)
```

A straightforward capture-then-playback pipeline. OS-level audio policy is never touched. Windows and Linux share the same code path (there is no per-platform file).

The tradeoff is added latency. Total added latency is governed by `chunk_seconds` on the capture side and `blocksize` on the output side. The default `chunk_seconds=0.02` (20 ms) is tuned for low latency.

______________________________________________________________________

## Basic usage

### Enumerate devices

```bash
vrcpilot speaker list
```

Prints the available output speakers as YAML on stdout. The entry with `is_default: true` is the OS default.

```yaml
devices:
  - id: "{0.0.0.00000000}.{...}"
    name: Speakers (Realtek High Definition Audio)
    is_default: true
  - id: "{0.0.0.00000000}.{...}"
    name: CABLE Input (VB-Audio Virtual Cable)
    is_default: false
```

### Start a relay

```bash
vrcpilot speaker route --pid 12345 --device "CABLE Input"
```

`--pid` is required (multi-instance is the assumed scenario, so the PID is never auto-resolved). `--device` accepts either an exact match on the `id` or `name` from `list`, or a case-insensitive substring match. If a fuzzy match resolves to more than one device the command errors out.

The command runs in the foreground. Ctrl+C stops it and exits with code 0. If the VRChat process dies the relay stops with exit code 1.

Omitting `--device` selects the **OS default speaker**. When the relay starts the resolved device name is printed once to stderr as `route: pid=12345 device='Speakers (Realtek)' (system default)`.

### Tune latency

```bash
vrcpilot speaker route --pid 12345 --device "CABLE Input" \
    --chunk-seconds 0.05 --blocksize 1024
```

- `--chunk-seconds` (default `0.02`): capture chunk size in seconds. Smaller means lower latency; larger means more headroom against underruns (audio dropouts).
- `--blocksize` (default `None` = soundcard default): output buffer size in frames.

______________________________________________________________________

## Virtual speaker devices

**Virtual speakers are optional.** Relaying directly to a physical speaker works fine. Reach for a virtual device only when you actually need multi-instance separation, or integration with another tool such as a DAW or streaming software.

### Windows

Common virtual-cable tools (most require a reboot after installation):

- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) — provides a single `CABLE Input → CABLE Output` pair. For multiple cables use the paid `CABLE A/B/C/D` editions.
- [VB-Audio Voicemeeter Banana](https://vb-audio.com/Voicemeeter/banana.htm) — 3 input strips plus 2 virtual cables. A solid choice when you also need mixing or monitoring.
- [Virtual Audio Cable (VAC)](https://vac.muzychenko.net/en/) — paid; create as many virtual cables as you want.

After install, confirm the new device shows up in `vrcpilot speaker list`.

### Linux

PipeWire can spin up virtual sinks on demand. **There is no need to install a long-running daemon up front.**

Create one ad hoc:

```bash
pactl load-module module-null-sink \
    sink_name=vrchat_pid_1 \
    sink_properties=device.description=VRChat_PID_1
```

`VRChat_PID_1` will then appear in `vrcpilot speaker list`. Unload with:

```bash
pactl unload-module $(pactl list short modules | grep vrchat_pid_1 | cut -f1)
```

To persist the sink across reboots, drop a config under `~/.config/pipewire/pipewire.conf.d/`. The `vrcpilot linux-mic register` family uses the same mechanism, so [`mic/linux.py`](../src/vrcpilot/mic/linux.py) is a useful reference implementation.

______________________________________________________________________

## Avoiding feedback loops with `vrcpilot mic`

`vrcpilot mic` already **uses VB-Audio Virtual Cable's `CABLE Input`**. Routing speaker output to that same cable closes the loop:

```
VRChat → speaker route → CABLE Input ─┐
                                              │
            CABLE Output → VRChat mic input ←┘ (configured inside VRChat)
```

Your own audio comes back to you as echo / howling.

Workarounds:

- Use a different virtual cable (install the paid editions for `CABLE-A Input` / `CABLE-B Input` and friends).
- Build a separate path through Voicemeeter or VAC.
- Skip virtual devices entirely and route directly to a physical speaker.

The same applies on Linux: keep the `VRCPilotMic` (mic side) and the relay destination on separate sinks.

______________________________________________________________________

## Windows: EarTrumpet integration

[EarTrumpet](https://eartrumpet.app/) is a free OSS tool (Microsoft Store / GitHub releases) that exposes per-application audio in a GUI. Two patterns combine well with vrcpilot:

**Pattern 1: single instance, no vrcpilot route**

If you only ever run one VRChat instance, point `VRChat.exe` directly to your output device through EarTrumpet. `vrcpilot speaker route` is not needed.

**Pattern 2: multi-instance hybrid**

Use EarTrumpet to send "all VRChat" to a virtual cable (e.g. `CABLE Input`), then split the individual PIDs back out with `vrcpilot speaker route --pid <N> --device <output>` per instance.

### Caveat

EarTrumpet drives `IAudioPolicyConfig` under the hood, which resolves AppIdentity from the exe path. That means **it cannot separate multiple instances of the same `VRChat.exe` per PID**. Per-instance separation remains vrcpilot relay's job.

______________________________________________________________________

## Linux: PipeWire GUI helpers

On PipeWire the following GUI tools handle per-application routing.

- [pavucontrol](https://freedesktop.org/software/pulseaudio/pavucontrol/) — GUI for PulseAudio (PipeWire's Pulse compatibility layer). The Playback tab lets you pick a sink per application. The closest UX equivalent to EarTrumpet.
- [Helvum](https://gitlab.freedesktop.org/pipewire/helvum) — a PipeWire-native graph editor. Wire streams to sinks with cables.
- [qpwgraph](https://gitlab.freedesktop.org/rncbc/qpwgraph) — same lineage as Helvum, Qt-based, more featureful.

Install examples:

```bash
# Debian / Ubuntu
sudo apt install pavucontrol helvum qpwgraph

# Fedora
sudo dnf install pavucontrol helvum qpwgraph

# Arch
sudo pacman -S pavucontrol helvum qpwgraph
```

### Caveat

Manual PipeWire wiring **comes undone every time VRChat restarts** — you would re-draw the cables in the GUI on every instance relaunch. For durable per-PID separation, prefer vrcpilot relay. The GUI tools are best suited to "single instance" or "hybrid setup (alongside vrcpilot route)".

______________________________________________________________________

## Latency tuning

Defaults are `chunk_seconds=0.02` (20 ms) and `blocksize=None` (soundcard default), biased toward low latency.

Decision flow:

1. Try the defaults first.
2. If audio drops out (underrun) or you hear crackles, raise `--chunk-seconds` step by step up to around `0.05`.
3. Still unstable? Increase the output buffer with `--blocksize 2048` or similar.
4. If the perceived latency is too high, you can also push `--chunk-seconds` down to `0.01` (tradeoff: more CPU load and higher underrun risk).

### Phase 6 e2e observations

- **Windows 11 (Ryzen / Realtek + VB-Cable + DELL monitor output)**: no underruns at the default `chunk_seconds=0.02`. Judging from transients such as VRChat launch sounds, mute toggles, and UI SFX, the perceived delay stays in the "conversational latency" range; A/B-ing against a `record`-captured waveform reveals little audible difference.
- Under the same conditions, two concurrent VRChat instances (`--profile 0` / `--profile 1`) were relayed independently — PID#1 to the built-in Realtek speakers, PID#2 to VB-Cable In 16ch. Both paths flowed through proc-tap → soundcard without interfering with each other, confirming per-PID separation that does not rely on any OS policy.
- The `integration_real` unit tests (`pytest -m integration_real tests/vrcpilot/speaker/routing/`) — 26 in total — all stay green in 2-3 seconds. Router start/stop cycling and empty-frame passthrough converge over real `soundcard` devices.
- **Known limitation**: if the VRChat process dies while a relay is running, the CLI stays parked in its `time.sleep` loop (internal `SpeakerLoop` exceptions only surface on the next `Router.stop()` by design). The user has to stop it explicitly with Ctrl+C. A future improvement (polling `Router.is_running` from the route loop) is out of scope for this release.
