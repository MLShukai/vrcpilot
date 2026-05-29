"""Unit + integration-real tests for :mod:`vrcpilot.screenshot`.

The autouse ``_no_real_vrchat`` fixture in :mod:`tests.conftest` leaves
:func:`vrcpilot.process.find_pids` returning ``[]``, so
:func:`take_screenshot` short-circuits at the focus step (``focus()``
returns ``False`` when ``resolve_pid`` raises) and returns ``None``
without ever opening a display or invoking ``mss``. This lets the
"VRChat not running" path be exercised on every host. The save/load
round-trip tests use real ``tmp_path`` + real PIL + real YAML, so the
on-disk schema is verified end-to-end without any mocking.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import yaml

from tests.fakes import write_screenshot_payload
from tests.helpers import only_linux
from vrcpilot.screenshot import Screenshot, take_screenshot


def _make_screenshot(
    *,
    width: int = 8,
    height: int = 4,
    x: int = 10,
    y: int = 20,
    monitor_index: int = 1,
    captured_at: datetime | None = None,
) -> Screenshot:
    """Build a real :class:`Screenshot` with a deterministic ndarray."""
    if captured_at is None:
        captured_at = datetime(2026, 5, 3, 12, 34, 56, 789012, tzinfo=timezone.utc)
    return Screenshot(
        image=np.zeros((height, width, 3), dtype=np.uint8),
        x=x,
        y=y,
        width=width,
        height=height,
        monitor_index=monitor_index,
        captured_at=captured_at,
    )


class TestTakeScreenshotInputValidation:
    """Pure unit-level validation tests — no platform branching involved."""

    @pytest.mark.parametrize("settle_seconds", [-0.001, -1.0])
    def test_negative_settle_seconds_raises_value_error(self, settle_seconds: float):
        with pytest.raises(ValueError, match="settle_seconds must be >= 0"):
            take_screenshot(settle_seconds=settle_seconds)


class TestTakeScreenshotShortCircuit:
    """No-VRChat short-circuit: focus() fails => take_screenshot() returns
    None.

    Uses the autouse ``_no_real_vrchat`` fixture so ``find_pids() == []``
    and ``resolve_pid(None)`` raises -> ``focus()`` returns False ->
    ``take_screenshot()`` returns None on every supported platform
    without ever needing a real display or ``mss`` grab.
    """

    def test_returns_none_when_vrchat_not_running(self):
        # Cross-platform short-circuit: focus() sees no PID and returns
        # False, take_screenshot() reflects that as None. Runs on both
        # Windows and Linux runners without any platform-specific setup.
        assert take_screenshot() is None

    @only_linux
    def test_returns_none_and_warns_on_wayland_native(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # Native Wayland (XDG_SESSION_TYPE=wayland and no DISPLAY) is
        # an explicitly unsupported configuration. The contract is to
        # emit RuntimeWarning AND return None so polling callers can
        # keep going rather than crash.
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.delenv("DISPLAY", raising=False)

        with pytest.warns(RuntimeWarning, match="Wayland native"):
            assert take_screenshot() is None


class TestScreenshotSavePathMode:
    """``Screenshot.save(png_path)`` writes the PNG and emits CLI YAML."""

    def test_writes_png_to_disk(self, tmp_path: Path):
        shot = _make_screenshot()
        png_path = tmp_path / "shot.png"

        shot.save(png_path)

        assert png_path.is_file()

    def test_yaml_payload_matches_screenshot_fields(self, tmp_path: Path):
        # The on-disk YAML must round-trip through ``yaml.safe_load`` to a
        # mapping whose values exactly mirror the source Screenshot
        # fields. This pins the CLI contract so downstream consumers
        # (``vrcpilot ocr``, ``vrcpilot detect``) can read it.
        shot = _make_screenshot()
        png_path = tmp_path / "shot.png"

        text = shot.save(png_path)

        loaded = yaml.safe_load(text)
        assert loaded == {
            "path": str(png_path.resolve()),
            "x": shot.x,
            "y": shot.y,
            "width": shot.width,
            "height": shot.height,
            "monitor_index": shot.monitor_index,
            "captured_at": shot.captured_at.isoformat(),
        }

    def test_yaml_keys_appear_in_documented_order(self, tmp_path: Path):
        # CLI consumers may parse the YAML line-by-line; the docstring
        # contract promises this specific order, so pin it.
        shot = _make_screenshot()

        text = shot.save(tmp_path / "shot.png")

        loaded = yaml.safe_load(text)
        assert list(loaded.keys()) == [
            "path",
            "x",
            "y",
            "width",
            "height",
            "monitor_index",
            "captured_at",
        ]

    def test_path_field_is_absolute_even_when_caller_passes_relative(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Operate from inside ``tmp_path`` so a relative path written by
        # the caller resolves to a known absolute location we can
        # compare against. The contract is that ``path:`` is always
        # absolute regardless of how the caller spelled it.
        monkeypatch.chdir(tmp_path)
        shot = _make_screenshot()

        text = shot.save(Path("shot.png"))

        path_value = yaml.safe_load(text)["path"]
        assert Path(path_value).is_absolute()
        assert Path(path_value) == (tmp_path / "shot.png").resolve()

    def test_raises_when_parent_directory_missing(self, tmp_path: Path):
        # Docstring: "The parent directory must already exist (callers do
        # their own ``mkdir(parents=True)``)." PIL raises FileNotFoundError
        # in that case and the helper propagates rather than swallowing.
        shot = _make_screenshot()
        target = tmp_path / "no_such_dir" / "shot.png"

        with pytest.raises(FileNotFoundError):
            shot.save(target)


class TestScreenshotSaveInlineMode:
    """``Screenshot.save()`` (no arg) base64-encodes the PNG inline."""

    def test_image_field_decodes_to_real_png_bytes(self):
        # The base64 image field must decode to a valid PNG (magic
        # bytes ``\x89PNG``); otherwise consumers cannot load it.
        shot = _make_screenshot()

        text = shot.save()

        loaded = yaml.safe_load(text)
        png_bytes = base64.b64decode(loaded["image"], validate=True)
        assert png_bytes.startswith(b"\x89PNG")

    def test_no_path_field_emitted(self):
        # In inline mode there is no on-disk PNG -- the ``path:`` key
        # must be absent so loaders can distinguish the two shapes.
        shot = _make_screenshot()

        text = shot.save()

        assert "path" not in yaml.safe_load(text)

    def test_image_key_appears_last_for_grep_friendliness(self):
        # Docstring promise: metadata first, then the (potentially huge)
        # image value -- so ``grep -v image:`` still surfaces metadata.
        shot = _make_screenshot()

        text = shot.save()

        keys = list(yaml.safe_load(text).keys())
        assert keys[-1] == "image"
        assert keys[:-1] == [
            "x",
            "y",
            "width",
            "height",
            "monitor_index",
            "captured_at",
        ]


class TestScreenshotRoundTrip:
    """``save()`` then ``load()`` must restore every field bit-for-bit."""

    def test_path_mode_round_trip_preserves_metadata(self, tmp_path: Path):
        shot = _make_screenshot()
        text = shot.save(tmp_path / "shot.png")

        restored = Screenshot.load(text)

        assert restored.x == shot.x
        assert restored.y == shot.y
        assert restored.width == shot.width
        assert restored.height == shot.height
        assert restored.monitor_index == shot.monitor_index
        assert restored.captured_at == shot.captured_at

    def test_path_mode_round_trip_preserves_image_shape_and_dtype(self, tmp_path: Path):
        shot = _make_screenshot(width=24, height=12)
        text = shot.save(tmp_path / "shot.png")

        restored = Screenshot.load(text)

        assert restored.image.shape == (12, 24, 3)
        assert restored.image.dtype == np.uint8

    def test_inline_mode_round_trip_preserves_metadata(self):
        shot = _make_screenshot(width=24, height=12, x=3, y=4, monitor_index=2)

        restored = Screenshot.load(shot.save())

        assert restored.x == 3
        assert restored.y == 4
        assert restored.width == 24
        assert restored.height == 12
        assert restored.monitor_index == 2

    def test_inline_mode_round_trip_preserves_image_shape_and_dtype(self):
        shot = _make_screenshot(width=24, height=12)

        restored = Screenshot.load(shot.save())

        assert restored.image.shape == (12, 24, 3)
        assert restored.image.dtype == np.uint8


class TestScreenshotLoadRejection:
    """``Screenshot.load`` must reject every malformed input shape."""

    def test_rejects_non_mapping_payload(self):
        # YAML lists / scalars are never valid screenshot payloads.
        text = yaml.safe_dump([1, 2, 3])

        with pytest.raises(ValueError, match="mapping"):
            Screenshot.load(text)

    @pytest.mark.parametrize(
        "missing_key",
        ["x", "y", "width", "height", "monitor_index", "captured_at"],
    )
    def test_rejects_missing_required_metadata_key(
        self, tmp_path: Path, missing_key: str
    ):
        # ``path`` xor ``image`` exclusivity is covered by separate
        # tests below; the other six metadata keys are unconditionally
        # required and missing any one of them must raise.
        _, yaml_text = write_screenshot_payload(tmp_path)
        payload = yaml.safe_load(yaml_text)
        del payload[missing_key]
        broken = yaml.safe_dump(payload, sort_keys=False)

        with pytest.raises(ValueError, match="invalid screenshot YAML"):
            Screenshot.load(broken)

    def test_rejects_uncoercible_field_value(self, tmp_path: Path):
        # ``x`` is documented as an int; a non-numeric string must fail
        # the ``int(payload["x"])`` cast and propagate as ValueError.
        _, yaml_text = write_screenshot_payload(tmp_path)
        payload = yaml.safe_load(yaml_text)
        payload["x"] = "abc"
        broken = yaml.safe_dump(payload, sort_keys=False)

        with pytest.raises(ValueError, match="invalid screenshot YAML"):
            Screenshot.load(broken)

    def test_rejects_invalid_captured_at_format(self, tmp_path: Path):
        # ``captured_at`` must be ISO 8601; ``datetime.fromisoformat``
        # raises ValueError for arbitrary strings and the helper
        # converts that into the schema-level error.
        _, yaml_text = write_screenshot_payload(tmp_path)
        payload = yaml.safe_load(yaml_text)
        payload["captured_at"] = "not-a-timestamp"
        broken = yaml.safe_dump(payload, sort_keys=False)

        with pytest.raises(ValueError, match="invalid screenshot YAML"):
            Screenshot.load(broken)

    def test_rejects_both_path_and_image(self, tmp_path: Path):
        # ``path`` and ``image`` are mutually exclusive: presence of
        # both is ambiguous about which to consume, so the loader must
        # refuse rather than pick one silently.
        _, yaml_text = write_screenshot_payload(tmp_path)
        payload = yaml.safe_load(yaml_text)
        # Borrow a well-formed image blob so the rejection is about
        # *both* keys being present, not a malformed image field.
        inline = yaml.safe_load(_make_screenshot().save())
        payload["image"] = inline["image"]
        broken = yaml.safe_dump(payload, sort_keys=False)

        with pytest.raises(ValueError, match="either 'path' or 'image', not both"):
            Screenshot.load(broken)

    def test_rejects_neither_path_nor_image(self, tmp_path: Path):
        # Absence of both keys leaves the loader with no image source.
        _, yaml_text = write_screenshot_payload(tmp_path)
        payload = yaml.safe_load(yaml_text)
        del payload["path"]
        broken = yaml.safe_dump(payload, sort_keys=False)

        with pytest.raises(ValueError, match="either 'path' or 'image'"):
            Screenshot.load(broken)

    def test_rejects_path_pointing_to_missing_png(self, tmp_path: Path):
        # File missing on disk: the error message must name the offending
        # path so the user can fix it (per docstring contract).
        _, yaml_text = write_screenshot_payload(tmp_path)
        payload = yaml.safe_load(yaml_text)
        payload["path"] = str(tmp_path / "does_not_exist.png")
        broken = yaml.safe_dump(payload, sort_keys=False)

        with pytest.raises(ValueError, match="PNG referenced by"):
            Screenshot.load(broken)

    def test_rejects_path_pointing_to_non_image_file(self, tmp_path: Path):
        # File exists but is not a real PNG: PIL raises
        # UnidentifiedImageError; the helper surfaces a schema-level
        # message that names the underlying failure.
        _, yaml_text = write_screenshot_payload(tmp_path)
        payload = yaml.safe_load(yaml_text)
        bogus = tmp_path / "not_an_image.png"
        bogus.write_bytes(b"this is not a PNG, just plain text")
        payload["path"] = str(bogus)
        broken = yaml.safe_dump(payload, sort_keys=False)

        with pytest.raises(ValueError, match="not a valid image"):
            Screenshot.load(broken)

    def test_rejects_invalid_base64_in_image_field(self):
        # Characters outside the base64 alphabet must be rejected with
        # validate=True. The loader surfaces this as the schema-level
        # error rather than letting ``binascii.Error`` escape.
        payload = yaml.safe_load(_make_screenshot().save())
        payload["image"] = "not-valid-base64-!@#"
        broken = yaml.safe_dump(payload, sort_keys=False)

        with pytest.raises(ValueError, match="invalid screenshot YAML"):
            Screenshot.load(broken)
