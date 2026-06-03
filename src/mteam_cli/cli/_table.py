"""ASCII table printer with CJK-aware column padding."""

from __future__ import annotations

import unicodedata


def cjk_visual_width(text: str) -> int:
    """Terminal display width: wide/fullwidth glyphs = 2, others = 1.

    Uses ``unicodedata.east_asian_width`` so it covers not just the CJK
    ideograph block but also fullwidth punctuation (， ： ！ etc.) and other
    East-Asian wide ranges that a hand-rolled range check misses — those are
    common in M-Team titles and would otherwise misalign every following column.
    """
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def pad_cell(text: str, width: int) -> str:
    """Pad a cell to the given visual width (CJK-aware)."""
    visible = cjk_visual_width(text)
    pad = max(0, width - visible)
    return f" {text}{' ' * pad} "


def print_table(headers: list[str], rows: list[tuple]) -> None:
    """Print a simple left-aligned table with auto-sized columns."""
    col_count = len(headers)
    widths = [cjk_visual_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < col_count:
                widths[i] = max(widths[i], cjk_visual_width(str(cell)))

    sep = "-" * (sum(widths) + 3 * col_count + 1)
    print(sep)

    header_parts = [pad_cell(h, widths[i]) for i, h in enumerate(headers)]
    print("|".join(header_parts))
    print(sep)

    for row in rows:
        parts = [pad_cell(str(cell), widths[i]) for i, cell in enumerate(row) if i < col_count]
        print("|".join(parts))

    print(sep)
