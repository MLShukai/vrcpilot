"""Single-shot VRChat window screenshot for GUI automation.

For continuous frames use :mod:`vrcpilot.capture`. This module focuses
VRChat first to guarantee captured pixels match what the user sees,
accepting the latency cost in exchange for accurate click coordinates.
Recoverable failures return ``None`` so polling callers can retry.
"""

from __future__ import annotations

import base64
import binascii
import io
import sys
import time
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import mss
import numpy as np
import yaml
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

from vrcpilot.geometry import get_vrchat_window_rect
from vrcpilot.session import is_wayland_native
from vrcpilot.window import focus


@dataclass(frozen=True, eq=False)
class Screenshot:
    """VRChat window pixel data plus its on-screen geometry.

    ``eq=False`` because numpy element-wise ``__eq__`` does not return a
    bool and so cannot back a dataclass-synthesised ``__eq__``. Frozen;
    use :func:`dataclasses.replace` for derived copies.

    Attributes:
        image: ``(H, W, 3)`` ``uint8`` RGB ndarray, detached from the
            capture buffer.
        x, y: Window-frame top-left in absolute desktop pixels at
            capture time. Informational only — :func:`mouse.move` takes
            window-local coordinates. May be negative on multi-monitor
            layouts.
        width, height: Window-frame size in physical pixels.
        monitor_index: Index into ``mss.MSS().monitors`` (``0`` is the
            composite). Falls back to ``0`` when the window centre lies
            outside every monitor.
        captured_at: UTC timestamp of the grab.
    """

    image: NDArray[np.uint8]
    x: int
    y: int
    width: int
    height: int
    monitor_index: int
    captured_at: datetime

    def save(self, png_path: Path | None = None) -> str:
        """Serialise to YAML so the CLI can pipe a screenshot to disk or
        stdout.

        Round-trippable through :meth:`load`. The single return type
        covers two emission modes so callers can always tee the result
        to a ``.yaml`` file or stdout, regardless of whether the PNG
        sits on disk or travels inline.

        Args:
            png_path: When provided, the PNG is written there and the
                YAML records its ``resolve()``-d absolute path (key
                order ``path, x, y, width, height, monitor_index,
                captured_at`` — the historical CLI contract). When
                omitted, the PNG bytes are base64-encoded under
                ``image:`` which is emitted **last** so metadata stays
                grep-friendly.

        Raises:
            FileNotFoundError: Path mode only; ``png_path``'s parent
                directory does not exist. Propagated from PIL — the
                caller is expected to ``mkdir(parents=True)`` first.
        """
        if png_path is not None:
            Image.fromarray(self.image).save(png_path)
            payload: dict[str, object] = {
                "path": str(png_path.resolve()),
                "x": self.x,
                "y": self.y,
                "width": self.width,
                "height": self.height,
                "monitor_index": self.monitor_index,
                "captured_at": self.captured_at.isoformat(),
            }
        else:
            buf = io.BytesIO()
            Image.fromarray(self.image).save(buf, format="PNG")
            payload = {
                "x": self.x,
                "y": self.y,
                "width": self.width,
                "height": self.height,
                "monitor_index": self.monitor_index,
                "captured_at": self.captured_at.isoformat(),
                "image": base64.b64encode(buf.getvalue()).decode("ascii"),
            }
        return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)

    @classmethod
    def load(cls, text: str) -> Screenshot:
        """Restore a :class:`Screenshot` from YAML produced by :meth:`save`.

        Accepts both emission shapes. Exactly one of ``path`` / ``image``
        must be present — both or neither is a :class:`ValueError` so
        the schema stays unambiguous. The returned ``image`` is detached
        from any underlying file/buffer, so callers can delete the
        source PNG immediately.

        Raises:
            ValueError: The payload is malformed — not a mapping,
                missing a required key, has an uncoercible field, a
                non-ISO-8601 ``captured_at``, invalid base64, or
                references a PNG that does not exist / is not a real
                image. The message names the offending field or file
                so the user can locate the breakage.
        """
        raw = yaml.safe_load(text)
        if not isinstance(raw, dict):
            raise ValueError("screenshot YAML must be a mapping")
        # ``yaml.safe_load`` returns ``dict[Unknown, Unknown]`` under
        # pyright strict; cast to a permissive ``dict[str, Any]`` so the
        # downstream ``int()`` / ``str()`` coercions are well-typed. The
        # actual type validation is performed at runtime via the
        # ``(binascii.Error, KeyError, TypeError, ValueError)`` catch
        # below.
        payload = cast(dict[str, Any], raw)
        has_path = "path" in payload
        has_image = "image" in payload
        if has_path and has_image:
            raise ValueError(
                "screenshot YAML must contain either 'path' or 'image', not both"
            )
        if not has_path and not has_image:
            raise ValueError("screenshot YAML must contain either 'path' or 'image'")
        try:
            if has_image:
                png_bytes = base64.b64decode(str(payload["image"]), validate=True)
                with Image.open(io.BytesIO(png_bytes)) as img:
                    image = np.asarray(img.convert("RGB"), dtype=np.uint8).copy()
            else:
                png_path = Path(str(payload["path"]))
                with Image.open(png_path) as img:
                    image = np.asarray(img.convert("RGB"), dtype=np.uint8).copy()
            return cls(
                image=image,
                x=int(payload["x"]),
                y=int(payload["y"]),
                width=int(payload["width"]),
                height=int(payload["height"]),
                monitor_index=int(payload["monitor_index"]),
                captured_at=datetime.fromisoformat(str(payload["captured_at"])),
            )
        except FileNotFoundError as exc:
            raise ValueError(
                f"PNG referenced by screenshot YAML not found: {exc.filename}"
            ) from exc
        except UnidentifiedImageError as exc:
            raise ValueError(
                f"PNG referenced by screenshot YAML is not a valid image: {exc}"
            ) from exc
        except (binascii.Error, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid screenshot YAML: {exc}") from exc


def _resolve_monitor_index(
    rect: tuple[int, int, int, int],
    monitors: Sequence[Mapping[str, Any]],
) -> int:
    """Return the mss-monitor index containing *rect*'s centre, or ``0``."""
    x, y, width, height = rect
    cx = x + width // 2
    cy = y + height // 2
    for i, mon in enumerate(monitors[1:], start=1):
        left = int(mon["left"])
        top = int(mon["top"])
        right = left + int(mon["width"])
        bottom = top + int(mon["height"])
        if left <= cx < right and top <= cy < bottom:
            return i
    return 0


def take_screenshot(
    *, settle_seconds: float = 0.05, pid: int | None = None
) -> Screenshot | None:
    """Grab one VRChat window screenshot suitable for GUI-automation clicking.

    The window is focused first so the captured pixels match what the
    user sees; for streaming pixels at native framerate use
    :mod:`vrcpilot.capture` instead.

    Args:
        settle_seconds: Post-focus sleep in seconds, giving the
            compositor time to finish raising the window before the
            grab. 50 ms is a generous margin for typical desktops.
        pid: Disambiguates when multiple VRChat instances run. When
            ``None``, :func:`vrcpilot.process.resolve_pid` picks the
            sole instance (or raises ``VRChatMultipleInstancesError``).

    Returns:
        A populated :class:`Screenshot`, or ``None`` on recoverable
        failure (Wayland native, focus refused, window not yet mapped,
        ``mss`` error). Returning ``None`` lets polling callers retry
        without try/except. The Wayland-native path additionally emits
        :class:`RuntimeWarning`; this asymmetry with
        :class:`vrcpilot.capture.Capture` (which raises) is deliberate
        so polling tolerates Wayland while streaming fails loudly.

    Raises:
        ValueError: ``settle_seconds`` is negative.
        NotImplementedError: Running on a platform other than Windows
            or Linux.
    """
    if settle_seconds < 0:
        raise ValueError("settle_seconds must be >= 0")

    # 1. Platform check
    if sys.platform == "linux":
        if is_wayland_native():
            warnings.warn(
                "Wayland native session detected; "
                "take_screenshot() requires X11 or XWayland.",
                RuntimeWarning,
                stacklevel=2,
            )
            return None
    elif sys.platform != "win32":
        raise NotImplementedError(
            f"take_screenshot() is not supported on {sys.platform}"
        )

    # 2. Focus
    if not focus(pid=pid):
        return None

    # 3. Settle
    time.sleep(settle_seconds)

    # 4. Window rectangle
    rect = get_vrchat_window_rect(pid=pid)
    if rect is None:
        return None
    x, y, width, height = rect

    # 5. mss grab + metadata.
    #
    # We hold the ``MSS`` instance in a local and call ``close()`` explicitly
    # (rather than ``with mss.MSS() as sct:``) so test fakes can be plain
    # ``mocker.Mock`` objects without having to also implement the context
    # manager protocol.
    sct = mss.MSS()
    try:
        region = {"left": x, "top": y, "width": width, "height": height}
        try:
            shot = sct.grab(region)
        except mss.ScreenShotError:
            return None
        captured_at = datetime.now(timezone.utc)
        # ``shot.rgb`` is a freshly-allocated bytes object derived from the
        # raw BGRA buffer; reshape via numpy and ``.copy()`` to detach from
        # the mss-owned buffer before ``sct.close()`` runs.
        image: NDArray[np.uint8] = (
            np.frombuffer(shot.rgb, dtype=np.uint8)
            .reshape(shot.size.height, shot.size.width, 3)
            .copy()
        )
        monitor_index = _resolve_monitor_index((x, y, width, height), sct.monitors)
    finally:
        sct.close()

    return Screenshot(
        image=image,
        x=x,
        y=y,
        width=width,
        height=height,
        monitor_index=monitor_index,
        captured_at=captured_at,
    )
