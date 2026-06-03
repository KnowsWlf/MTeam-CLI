"""Formatting helpers for M-Team numeric fields (bytes / ratio)."""

from __future__ import annotations

import humanize as _humanize


def naturalsize(value: object) -> str:
    """Human-readable binary size (MiB/GiB), matching the legacy script.

    Coerces via ``float`` first so a byte count that arrives as a float- or
    scientific-notation string (e.g. ``"12345.0"`` / ``"1.5e10"``) still
    formats instead of falling through to an unscaled raw string.
    """
    if value in (None, ""):
        return _humanize.naturalsize(0, binary=True)
    try:
        return _humanize.naturalsize(int(float(value)), binary=True)
    except (TypeError, ValueError):
        return str(value)


def ratio(value: object) -> str:
    """Share ratio as a string; M-Team sometimes returns a sentinel for ∞."""
    if value in (None, "", "-1", -1):
        return "∞"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def num(value: object) -> str:
    """Thousands-separated integer string; pass through on failure."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value if value is not None else "")
