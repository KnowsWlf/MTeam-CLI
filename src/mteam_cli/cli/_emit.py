"""Multi-format row emitter for query commands.

Every query command produces a list of dict rows + a field spec (column key +
display label). ``emit_rows`` renders to one of:

  * ``table``  — CJK-width-aware ASCII (human default)
  * ``json``   — pretty-printed JSON array
  * ``yaml``   — YAML list
  * ``csv``    — RFC 4180 CSV with header row
  * ``md``     — GitHub-flavored Markdown pipe table
  * ``plain``  — tab-separated values, no header (greppable / awkable)

JSON / YAML / CSV are pipe-clean (no banner, no footer) so they can be piped
to ``jq`` or fed to an LLM. Footer text prints only for table / md / plain.
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from typing import Any

import yaml

from mteam_cli.cli._table import cjk_visual_width

VALID_FORMATS = ("table", "json", "yaml", "csv", "md", "plain")
DEFAULT_FORMAT = "table"


@dataclass(slots=True)
class Field:
    """One output column: stable ``key`` for JSON/YAML, ``label`` for tables."""

    key: str
    label: str


def emit_rows(
    rows: list[dict[str, Any]],
    fields: list[Field],
    fmt: str = DEFAULT_FORMAT,
    footer: str = "",
) -> None:
    """Render rows in the requested format to stdout."""
    if fmt == "table":
        _emit_table(rows, fields)
        if footer:
            print(footer)
    elif fmt == "json":
        json.dump(
            [{f.key: r.get(f.key) for f in fields} for r in rows],
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
    elif fmt == "yaml":
        sys.stdout.write(
            yaml.safe_dump(
                [{f.key: r.get(f.key) for f in fields} for r in rows],
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
        )
    elif fmt == "csv":
        writer = csv.writer(sys.stdout)
        writer.writerow([f.label for f in fields])
        for r in rows:
            writer.writerow([_stringify(r.get(f.key)) for f in fields])
    elif fmt == "md":
        _emit_markdown(rows, fields)
        if footer:
            print()
            print(footer)
    elif fmt == "plain":
        for r in rows:
            print("\t".join(_stringify(r.get(f.key)) for f in fields))
        if footer:
            print(footer)
    else:
        raise ValueError(f"Unsupported format: {fmt!r} (choose from {VALID_FORMATS})")


def emit_record(
    record: dict[str, Any],
    fields: list[Field],
    fmt: str = DEFAULT_FORMAT,
) -> None:
    """Render a single key-value record (e.g. ``profile``).

    For ``table``/``md``/``plain``: prints ``label:    value`` lines.
    For ``json``/``yaml``/``csv``: treats it as a one-row list.
    """
    if fmt in ("json", "yaml", "csv"):
        emit_rows([record], fields, fmt=fmt)
        return
    label_width = max(cjk_visual_width(f.label) for f in fields) + 2
    for f in fields:
        value = _stringify(record.get(f.key, ""))
        pad = max(0, label_width - cjk_visual_width(f.label))
        print(f"{f.label}{' ' * pad}{value}")


# ── helpers ────────────────────────────────────────────────────


def _emit_table(rows: list[dict[str, Any]], fields: list[Field]) -> None:
    from mteam_cli.cli._table import print_table

    print_table(
        headers=[f.label for f in fields],
        rows=[tuple(_stringify(r.get(f.key)) for f in fields) for r in rows],
    )


def _emit_markdown(rows: list[dict[str, Any]], fields: list[Field]) -> None:
    print("| " + " | ".join(f.label for f in fields) + " |")
    print("| " + " | ".join("---" for _ in fields) + " |")
    for r in rows:
        cells = [_stringify(r.get(f.key)).replace("|", "\\|") for f in fields]
        print("| " + " | ".join(cells) + " |")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def auto_fields(rows: list[dict[str, Any]], max_cols: int = 8) -> list[Field]:
    """Derive a Field list from the rows' own keys (first-seen order).

    Used by commands whose exact response shape is not yet pinned down, so
    ``table``/``json`` still surface the real data instead of empty columns.
    Caps table-friendly width at ``max_cols`` keys.
    """
    seen: list[str] = []
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.append(k)
    return [Field(k, k) for k in seen[:max_cols]]


def has_nested_values(rows: list[dict[str, Any]]) -> bool:
    """True if any row has a dict/list value (renders as ugly repr in a table).

    Lets auto_fields-based commands warn the user to use ``--raw`` for a usable
    view, instead of silently emitting ``{'id': 1, ...}`` repr cells.
    """
    return any(
        isinstance(v, (dict, list)) for r in rows for v in r.values()
    )


def add_format_arg(parser: Any) -> None:
    """Inject ``-f/--format`` onto a subparser. Single source of truth."""
    parser.add_argument(
        "-f",
        "--format",
        dest="output_format",
        default=DEFAULT_FORMAT,
        choices=VALID_FORMATS,
        help=f"输出格式 (默认: {DEFAULT_FORMAT})",
    )


def add_raw_arg(parser: Any) -> None:
    """Inject ``--raw`` — dump the full, unprojected API ``data`` as JSON.

    The curated columns are for humans; ``--raw`` gives downstream logic / LLMs
    every field the API returned, no code change needed.
    """
    parser.add_argument(
        "--raw",
        action="store_true",
        help="输出 API 返回的完整原始 JSON（不做字段精选，便于下游/AI 消费）。",
    )


def emit_raw(data: Any) -> None:
    """Pretty-print the full API payload as JSON to stdout (pipe-clean)."""
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def notice(message: str) -> None:
    """Write a human diagnostic (error / empty-result hint) to stderr.

    Keeps stdout pipe-clean for the machine formats — an error or empty result
    under ``-f json`` must never put non-JSON text on stdout.
    """
    print(message, file=sys.stderr)
