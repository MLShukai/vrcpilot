---
name: vrcpilot capture vs screenshot API split
description: Two-pronged pixel-grab public surface — Capture (streaming) vs Screenshot (one-shot) — and the design rationale that docstrings should reinforce
metadata:
  type: project
---

vrcpilot's pixel-grab public surface is intentionally split into two
non-overlapping entry points, each with a distinct workload contract:

- `vrcpilot.Capture` (in `src/vrcpilot/capture.py`) — long-lived
  session, focus-free (does NOT raise the window), latest-only
  read semantics (NOT FIFO), backed by WGC on Windows / X11
  Composite on Linux.
- `vrcpilot.take_screenshot()` returning `Screenshot` (in
  `src/vrcpilot/screenshot.py`) — single-shot, calls `focus()` first,
  carries on-screen geometry (`x`, `y`, `width`, `height`,
  `monitor_index`, `captured_at`) so callers can translate in-image
  coordinates to absolute desktop coordinates for clicking / OCR.

**Why:** The streaming path optimises for "what's on screen *now*"
even when occluded; the one-shot path optimises for "match what the
user sees" and exposes the geometry that GUI automation needs. Mixing
them into one API would force every caller to handle both modes.

**Notable asymmetries to highlight in docstrings:**

- Wayland native: `Capture` raises `RuntimeError` (streaming has
  nothing to fall back to), `take_screenshot` warns + returns `None`
  (polling callers can recover). Always explain *why* the asymmetry
  exists.
- Failure surface: `take_screenshot` returns `None` on every
  recoverable failure (focus refused, window not yet mapped, transient
  mss error) so polling callers don't need to catch. Programming
  errors (bad platform, bad args) still raise.
- `Capture.read()` is **latest-only**, not FIFO. This is a deliberate
  video-workload choice and worth calling out — readers expect FIFO
  by default.

**How to apply:** When documenting either module, always include a
cross-reference to the other and a one-sentence "use this when..."
guide. The `__init__.py` module docstring is the canonical place for
the side-by-side comparison; capture/screenshot module docstrings
should each reiterate the chooser briefly. The internal design memo
that captures the full rationale lives at
`memory/agents/spec-planner/capture_screenshot_internal_design.md`.
