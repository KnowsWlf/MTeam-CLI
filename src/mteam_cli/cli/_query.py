"""Shared scaffolding for the data-query commands.

Every data command repeats the same tail: await an API call, turn
``MTeamAPIError`` into a stderr diagnostic + exit 1, and short-circuit to raw
JSON when ``--raw`` is set. Centralizing it here keeps that error/--raw/exit
contract in ONE place so the 7 commands can't drift (they did before this).

Commands still own what legitimately differs: account/session resolution and
the row/record shaping.
"""

from __future__ import annotations

import argparse
from typing import Any, Awaitable

from mteam_cli.api import MTeamAPIError
from mteam_cli.cli._emit import emit_raw, notice


class QueryExit(Exception):
    """Raised to unwind a command with a specific exit code (already reported)."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


async def fetch(coro: Awaitable[Any]) -> Any:
    """Await an API coroutine, converting ``MTeamAPIError`` to exit 1.

    On error: writes ``错误: ...`` to stderr (keeping stdout pipe-clean) and
    raises ``QueryExit(1)``. The command's ``handle`` wraps its body so this
    unwinds cleanly — see ``run``.
    """
    try:
        return await coro
    except MTeamAPIError as exc:
        notice(f"错误: {exc}")
        raise QueryExit(1) from exc


def maybe_raw(args: argparse.Namespace, data: Any) -> bool:
    """If ``--raw`` was passed, dump the full payload and signal done.

    Returns ``True`` when raw output was emitted (the command should return 0).
    """
    if getattr(args, "raw", False):
        emit_raw(data)
        return True
    return False


async def run(body: Awaitable[int]) -> int:
    """Run a command body, translating a ``QueryExit`` into its exit code.

    Lets command handlers call ``fetch``/``maybe_raw`` and shape data linearly
    without nesting try/except in every file.
    """
    try:
        return await body
    except QueryExit as exit_:
        return exit_.code
