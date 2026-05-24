"""Tests for :mod:`vrcpilot.types`.

``vrcpilot.types`` holds shared type aliases used by both
``vrcpilot.ocr`` and ``vrcpilot.detect``. The aliases are PEP 695
``type`` statements: their static shape is enforced by pyright, but
the *runtime* alias object also encodes the structure (via
``__value__``), and downstream code reads that structure to do
introspection (e.g. tooling, docs). This file pins the runtime
structure so a refactor that silently changes the alias shape (e.g.
adding a 5th corner or swapping ``float`` for ``int``) is caught.
"""

from __future__ import annotations

from typing import get_args, get_origin

from vrcpilot.types import Polygon


class TestPolygonShape:
    """``Polygon`` is a 4-corner polygon of 2D float coordinates.

    The docstring in ``vrcpilot.types`` calls out the ordering as
    ``TL, TR, BR, BL`` and "image-local pixels". Ordering is not
    encoded in the type system (all four corners have the same
    ``tuple[float, float]`` shape), so this file only pins what the
    runtime alias can prove: arity 4 and a per-corner shape of
    ``tuple[float, float]``.
    """

    def test_is_a_4_tuple_of_2d_float_corners(self) -> None:
        # ``type Polygon = tuple[X, X, X, X]`` materialises at runtime
        # as a generic alias whose ``__value__`` is the underlying
        # ``tuple[...]`` annotation. ``get_origin`` / ``get_args``
        # peel that back to ``tuple`` and the four corner types.
        underlying = Polygon.__value__

        assert get_origin(underlying) is tuple

        corners = get_args(underlying)
        assert len(corners) == 4
        for corner in corners:
            assert get_origin(corner) is tuple
            assert get_args(corner) == (float, float)
