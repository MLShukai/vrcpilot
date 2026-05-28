"""Single-shot VRChat window screenshot for GUI automation.

For continuous frames use :mod:`vrcpilot.capture`. This module captures
the VRChat window contents directly via :class:`vrcpilot.capture.Capture`
so the pixel origin ``(0, 0)`` matches window-local coordinates used by
OCR / detect / mouse. Recoverable failures return ``None`` so polling
callers can retry.
"""

from __future__ import annotations

import base64
import binascii
import io
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import numpy as np
import yaml
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

from vrcpilot.capture import Capture
from vrcpilot.geometry import get_vrchat_window_rect
from vrcpilot.session import is_wayland_native


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
        width, height: Window-frame size in physical pixels, taken from
            the captured image, so ``image.shape == (height, width, 3)``
            holds unconditionally.
        monitor_index: Deprecated field kept for backward compatibility.
            ``take_screenshot()`` always sets it to ``0``. Scheduled for
            removal in 0.6.0; constructing with a non-zero value emits a
            :class:`DeprecationWarning`.
        captured_at: UTC timestamp of the capture.
    """

    image: NDArray[np.uint8]
    x: int
    y: int
    width: int
    height: int
    monitor_index: int
    captured_at: datetime

    def __post_init__(self) -> None:
        """Warn when the deprecated ``monitor_index`` carries a non-zero value.

        ``monitor_index`` is retained only for backward compatibility and
        will be removed in 0.6.0. ``take_screenshot()`` always sets ``0``,
        so the normal capture / ``save()`` / CLI pipeline never warns; the
        warning fires only when a non-zero value is constructed explicitly
        or restored from YAML via :meth:`load`.
        """
        if self.monitor_index != 0:
            warnings.warn(
                "Screenshot.monitor_index is deprecated and will be removed "
                "in 0.6.0",
                DeprecationWarning,
                stacklevel=2,
            )

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


def take_screenshot(*, pid: int | None = None) -> Screenshot | None:
    """Capture one VRChat window screenshot suitable for GUI-automation
    clicking.

    Captures the window contents directly via
    :class:`vrcpilot.capture.Capture`, so the image origin ``(0, 0)``
    coincides with the window-local origin used by OCR / detect / mouse.
    For streaming pixels at native framerate use :mod:`vrcpilot.capture`
    instead.

    The window is not focused or raised before capture; window-content
    capture reads the framebuffer regardless of foreground state.

    Args:
        pid: Disambiguates when multiple VRChat instances run. When
            ``None``, :func:`vrcpilot.process.resolve_pid` (via
            :func:`vrcpilot.geometry.get_vrchat_window_rect`) picks the
            sole instance (or raises ``VRChatMultipleInstancesError``).

    Returns:
        A populated :class:`Screenshot`, or ``None`` on recoverable
        failure: Wayland native session, VRChat not running, window not
        yet mapped, or a backend ``RuntimeError`` / ``TimeoutError``.
        Returning ``None`` lets polling callers retry without try/except.
        The Wayland-native path additionally emits :class:`RuntimeWarning`;
        this asymmetry with :class:`vrcpilot.capture.Capture` (which
        raises) is deliberate so polling tolerates Wayland while
        streaming fails loudly.

    Raises:
        NotImplementedError: Running on a platform other than Windows
            or Linux.
        VRChatMultipleInstancesError: ``pid`` is ``None`` and multiple
            VRChat instances are running (propagated from
            :func:`vrcpilot.geometry.get_vrchat_window_rect`).
    """
    # 1. Platform check.
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

    # 2. Window rectangle. ``get_vrchat_window_rect`` owns pid resolution:
    # it converts ``VRChatNotRunningError`` to ``None`` and re-raises the
    # ``VRChatMultipleInstancesError`` subclass. Passing ``pid`` straight
    # through (rather than resolving it here) avoids the subclass trap of
    # swallowing the multi-instance error.
    rect = get_vrchat_window_rect(pid=pid)
    if rect is None:
        return None
    x, y, _w, _h = rect

    # 3-6. Capture one frame. ``RuntimeError`` / ``TimeoutError`` are
    # recoverable backend failures absorbed as ``None`` so polling callers
    # can retry; ``NotImplementedError`` (unsupported platform) propagates.
    try:
        with Capture(pid=pid) as cap:
            image = cap.read()
            captured_at = datetime.now(timezone.utc)
    except (RuntimeError, TimeoutError):
        return None

    image = np.ascontiguousarray(image, dtype=np.uint8)

    # 7. ``width`` / ``height`` come from the captured image (not the rect)
    # so ``image.shape == (height, width, 3)`` holds unconditionally.
    return Screenshot(
        image=image,
        x=x,
        y=y,
        width=image.shape[1],
        height=image.shape[0],
        monitor_index=0,
        captured_at=captured_at,
    )
