"""Unit + integration-real tests for :mod:`vrcpilot.screenshot`.

``take_screenshot()`` no longer focuses the window or sleeps; it asks
:func:`vrcpilot.geometry.get_vrchat_window_rect` for the desktop rect
and then grabs a single frame through the in-house
:class:`vrcpilot.Capture` abstraction. Two test doubles substitute the
vrcpilot-*own* collaborators (never a 3rd-party surface like ``mss`` /
``windows_capture`` / ``Xlib``):

* ``mocker.patch("vrcpilot.screenshot.Capture", return_value=FakeCapture(...))``
  swaps the own-ABC :class:`vrcpilot.Capture` for the shared
  :class:`tests.fakes.FakeCapture` (default frame ``np.zeros((4, 4, 3),
  uint8)``; ``read_side_effect`` injects backend failures).
* ``mocker.patch("vrcpilot.screenshot.get_vrchat_window_rect", ...)``
  swaps the vrcpilot-own rect helper.

The autouse ``_no_real_vrchat`` fixture in :mod:`tests.conftest` leaves
:func:`vrcpilot.process.find_pids` returning ``[]``, so the real
``get_vrchat_window_rect`` resolves no PID and returns ``None`` on every
host; this lets the "VRChat not running" short-circuit be exercised
without a real display or backend. The save/load round-trip tests use
real ``tmp_path`` + real PIL + real YAML, so the on-disk schema is
verified end-to-end without any mocking.

Note on the ``monitor_index`` deprecation: constructing a
:class:`Screenshot` with a non-zero ``monitor_index`` emits a
``DeprecationWarning`` (spec 2.3.3). The global
``filterwarnings = ["ignore::DeprecationWarning"]`` silently ignores it,
so helpers that build non-zero shots (e.g. :func:`_make_screenshot`,
which defaults to ``monitor_index=1``) stay green WITHOUT being wrapped
in ``pytest.warns`` -- wrapping them would wrongly *require* the warning.
The warning is asserted explicitly only in
:class:`TestScreenshotMonitorIndexDeprecation`.
"""

from __future__ import annotations

import base64
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import yaml
from pytest_mock import MockerFixture

from tests.fakes import FakeCapture, write_screenshot_payload
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
    """Build a real :class:`Screenshot` with a deterministic ndarray.

    Defaults ``monitor_index=1`` (non-zero). That construction emits a
    ``DeprecationWarning`` which the global ``filterwarnings`` ignore
    filter swallows, so callers must NOT wrap this in ``pytest.warns``
    (see the module docstring).
    """
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


class TestTakeScreenshotHappyPath:
    """Rect + a real frame from ``Capture`` produce a populated Screenshot.

    Patches the two vrcpilot-own collaborators only: the rect helper
    returns ``(100, 200, 800, 600)`` and ``Capture`` yields a
    :class:`FakeCapture` whose default frame is ``(4, 4, 3)``. The rect
    width/height (800/600) deliberately differ from the frame's (4/4)
    so the assertions can pin that ``width``/``height`` are
    *image-derived*, not rect-derived (spec 2.1).
    """

    def test_returns_screenshot_with_image_derived_dimensions(
        self, mocker: MockerFixture
    ):
        # Spec 2.1 / 2.2 / D-1: width and height come from the captured
        # image shape, NOT from the window rect, so the invariant
        # ``image.shape == (height, width, 3)`` holds unconditionally.
        mocker.patch(
            "vrcpilot.screenshot.get_vrchat_window_rect",
            return_value=(100, 200, 800, 600),
        )
        mocker.patch("vrcpilot.screenshot.Capture", return_value=FakeCapture())

        shot = take_screenshot()

        assert shot is not None
        assert shot.image.shape == (4, 4, 3)
        assert shot.width == 4  # image-derived, not rect's 800
        assert shot.height == 4  # image-derived, not rect's 600

    def test_x_and_y_come_from_window_rect(self, mocker: MockerFixture):
        # Spec 2.1 / D-1: x and y are informational, taken from the
        # rect helper's first two components.
        mocker.patch(
            "vrcpilot.screenshot.get_vrchat_window_rect",
            return_value=(100, 200, 800, 600),
        )
        mocker.patch("vrcpilot.screenshot.Capture", return_value=FakeCapture())

        shot = take_screenshot()

        assert shot is not None
        assert shot.x == 100
        assert shot.y == 200

    def test_monitor_index_is_always_zero(self, mocker: MockerFixture):
        # Spec 2.3 / D-1: take_screenshot() always sets monitor_index to
        # 0 (the deprecated field's post-removal default), so it never
        # trips the __post_init__ deprecation warning.
        mocker.patch(
            "vrcpilot.screenshot.get_vrchat_window_rect",
            return_value=(100, 200, 800, 600),
        )
        mocker.patch("vrcpilot.screenshot.Capture", return_value=FakeCapture())

        shot = take_screenshot()

        assert shot is not None
        assert shot.monitor_index == 0

    def test_captured_at_is_utc_aware(self, mocker: MockerFixture):
        # Spec 3.1 / D-1: the timestamp is taken immediately after the
        # frame read and must be timezone-aware in UTC (utcoffset == 0).
        mocker.patch(
            "vrcpilot.screenshot.get_vrchat_window_rect",
            return_value=(100, 200, 800, 600),
        )
        mocker.patch("vrcpilot.screenshot.Capture", return_value=FakeCapture())

        shot = take_screenshot()

        assert shot is not None
        assert shot.captured_at.tzinfo is not None
        assert shot.captured_at.utcoffset() == timezone.utc.utcoffset(None)

    def test_image_is_uint8(self, mocker: MockerFixture):
        # Spec 2.2 step 6 / D-1: the frame is normalised to a uint8
        # array before being stored on the Screenshot.
        mocker.patch(
            "vrcpilot.screenshot.get_vrchat_window_rect",
            return_value=(100, 200, 800, 600),
        )
        mocker.patch("vrcpilot.screenshot.Capture", return_value=FakeCapture())

        shot = take_screenshot()

        assert shot is not None
        assert shot.image.dtype == np.uint8


class TestTakeScreenshotRecoverableFailures:
    """Recoverable failures resolve to ``None`` so pollers can retry."""

    def test_returns_none_when_rect_is_none(self, mocker: MockerFixture):
        # Spec 2.2 step 2 / D-2: get_vrchat_window_rect returning None
        # (VRChat not running OR window unmapped) short-circuits to
        # None. Capture must never be constructed in this case.
        mocker.patch("vrcpilot.screenshot.get_vrchat_window_rect", return_value=None)
        capture_mock = mocker.patch("vrcpilot.screenshot.Capture")

        assert take_screenshot() is None
        capture_mock.assert_not_called()

    def test_returns_none_when_capture_read_raises_runtime_error(
        self, mocker: MockerFixture
    ):
        # Spec 2.2 step 4 / D-3: a RuntimeError from the backend
        # (window unmapped, no display, WGC session failure, ...) is a
        # recoverable failure that is absorbed into None.
        mocker.patch(
            "vrcpilot.screenshot.get_vrchat_window_rect",
            return_value=(100, 200, 800, 600),
        )
        mocker.patch(
            "vrcpilot.screenshot.Capture",
            return_value=FakeCapture(read_side_effect=RuntimeError("backend failed")),
        )

        assert take_screenshot() is None

    def test_returns_none_when_capture_read_times_out(self, mocker: MockerFixture):
        # Spec 2.2 step 4 / D-4: a TimeoutError (WGC frame-wait timeout)
        # is the other recoverable failure absorbed into None.
        mocker.patch(
            "vrcpilot.screenshot.get_vrchat_window_rect",
            return_value=(100, 200, 800, 600),
        )
        mocker.patch(
            "vrcpilot.screenshot.Capture",
            return_value=FakeCapture(read_side_effect=TimeoutError("no frame")),
        )

        assert take_screenshot() is None


class TestTakeScreenshotShortCircuit:
    """Short-circuits that need no patched collaborators."""

    def test_returns_none_when_vrchat_not_running(self):
        # Spec 2.2 step 2 / D-6: with the autouse ``_no_real_vrchat``
        # fixture, ``process_iter`` is empty so ``resolve_pid(None)``
        # raises ``VRChatNotRunningError``; ``get_vrchat_window_rect``
        # converts that to ``None`` and ``take_screenshot()`` returns
        # ``None``. (The reason is now "get_vrchat_window_rect returns
        # None", not the removed "focus() returns False" path.) Runs on
        # both Windows and Linux runners without any platform setup.
        assert take_screenshot() is None

    @only_linux
    def test_returns_none_and_warns_on_wayland_native(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # Spec 2.2 step 1 / D-5: native Wayland (XDG_SESSION_TYPE=wayland
        # and no DISPLAY) is an explicitly unsupported configuration.
        # The contract is to emit RuntimeWarning AND return None so
        # polling callers can keep going rather than crash. This path
        # short-circuits before get_vrchat_window_rect / Capture, so no
        # patching is needed.
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.delenv("DISPLAY", raising=False)

        with pytest.warns(RuntimeWarning, match="Wayland native"):
            assert take_screenshot() is None


class TestTakeScreenshotPidPropagation:
    """``pid`` flows unchanged to both collaborators (subclass-trap safe)."""

    def test_pid_is_forwarded_to_rect_helper_and_capture(self, mocker: MockerFixture):
        # Spec 2.2 step 2/4 / D-10: take_screenshot must NOT resolve the
        # pid itself (that would swallow VRChatMultipleInstancesError, a
        # subclass of VRChatNotRunningError). It passes the same pid
        # straight through to get_vrchat_window_rect and Capture, which
        # this test pins by inspecting both call records.
        rect_mock = mocker.patch(
            "vrcpilot.screenshot.get_vrchat_window_rect",
            return_value=(100, 200, 800, 600),
        )
        capture_mock = mocker.patch(
            "vrcpilot.screenshot.Capture", return_value=FakeCapture()
        )

        take_screenshot(pid=4242)

        assert rect_mock.call_args.kwargs["pid"] == 4242
        assert capture_mock.call_args.kwargs["pid"] == 4242


class TestTakeScreenshotUnsupportedPlatform:
    """Non-win32/linux platforms raise instead of returning None."""

    def test_raises_not_implemented_error_on_unsupported_platform(
        self, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
    ):
        # Spec 2.2 step 1 / D-11: an unsupported sys.platform must raise
        # NotImplementedError (propagated, never absorbed into None).
        # The platform check happens first, so neither collaborator is
        # reached; patch them so the test cannot accidentally hit a real
        # backend if the implementation order regresses.
        monkeypatch.setattr("vrcpilot.screenshot.sys.platform", "darwin")
        mocker.patch("vrcpilot.screenshot.get_vrchat_window_rect")
        mocker.patch("vrcpilot.screenshot.Capture")

        with pytest.raises(NotImplementedError):
            take_screenshot()


class TestScreenshotMonitorIndexDeprecation:
    """``monitor_index != 0`` construction emits a ``DeprecationWarning``.

    Spec 2.3.3 (candidate A): ``__post_init__`` warns only when the
    deprecated field is given a non-zero value -- i.e. when the
    soon-to-be-removed feature is actually used. Zero (the post-removal
    default) is silent so the internal serialization paths
    (``save()`` / ``cli/ocr.py`` / ``cli/detect.py``) never warn.
    """

    def test_nonzero_monitor_index_warns_about_removal_in_0_6_0(self):
        # Spec 2.3.3 / D-8: constructing with a non-zero monitor_index
        # warns, and the message names the 0.6.0 removal milestone.
        captured_at = datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)

        with pytest.warns(DeprecationWarning, match="0.6.0"):
            Screenshot(
                image=np.zeros((4, 4, 3), dtype=np.uint8),
                x=0,
                y=0,
                width=4,
                height=4,
                monitor_index=1,
                captured_at=captured_at,
            )

    def test_nonzero_monitor_index_warning_names_the_field(self):
        # Spec 2.3.3 / D-8 (MAY): the message also names the deprecated
        # field so users know what to stop using.
        captured_at = datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)

        with pytest.warns(DeprecationWarning, match="monitor_index"):
            Screenshot(
                image=np.zeros((4, 4, 3), dtype=np.uint8),
                x=0,
                y=0,
                width=4,
                height=4,
                monitor_index=2,
                captured_at=captured_at,
            )

    def test_zero_monitor_index_does_not_warn(self):
        # Spec 2.3.3 / D-8: monitor_index=0 must be silent. The global
        # ``ignore::DeprecationWarning`` filter would mask a real
        # warning, so escalate it to an error locally and assert that
        # construction does NOT raise.
        captured_at = datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            Screenshot(
                image=np.zeros((4, 4, 3), dtype=np.uint8),
                x=0,
                y=0,
                width=4,
                height=4,
                monitor_index=0,
                captured_at=captured_at,
            )

    def test_load_of_nonzero_monitor_index_warns(self, tmp_path: Path):
        # Spec 2.3.3 table / D-8: restoring a YAML payload whose
        # monitor_index is non-zero reconstructs a Screenshot with that
        # value, so the construction warning fires through load().
        _, yaml_text = write_screenshot_payload(tmp_path)
        payload = yaml.safe_load(yaml_text)
        payload["monitor_index"] = 1
        text = yaml.safe_dump(payload, sort_keys=False)

        with pytest.warns(DeprecationWarning, match="0.6.0"):
            Screenshot.load(text)

    def test_load_of_zero_monitor_index_does_not_warn(self, tmp_path: Path):
        # Spec 2.3.3 table / D-8: restoring monitor_index=0 is silent.
        # Escalate DeprecationWarning to an error to bypass the global
        # ignore filter and assert load() does not raise.
        _, yaml_text = write_screenshot_payload(tmp_path)
        payload = yaml.safe_load(yaml_text)
        payload["monitor_index"] = 0
        text = yaml.safe_dump(payload, sort_keys=False)

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            Screenshot.load(text)


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
