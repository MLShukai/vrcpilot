---
name: vrcpilot project purpose
description: vrcpilot is a Python library that automates VRChat — both Steam-level launch/UI and in-game OSC-driven actions.
type: project
---

vrcpilot is a Python library for automating VRChat. Scope spans:

- **Launch / process control**: spawning VRChat through Steam, terminating it (see `src/vrcpilot/process.py`).
- **VRChat client UI operations**: driving the desktop client (planned).
- **In-game operations**: typically via OSC and other VRChat-exposed surfaces.

**Why:** Built to remove repetitive manual steps when running VRChat for testing, scripting, or unattended sessions. Many features will compose on top of "VRChat is already running and reachable," so the launcher layer is a foundational primitive.

**How to apply:**

- Frame docstrings around the higher-level automation use case, not the raw subprocess call. Public APIs are entry points for downstream automation, so callers care about preconditions ("Steam must be installed", "process is detached so the script can exit") more than implementation steps.
- Use VRChat-native vocabulary: `--osc`, `--no-vr`, `-screen-width` (Unity convention), Steam `-applaunch`.
