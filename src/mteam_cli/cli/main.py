"""Argparse dispatcher.

Each subcommand module under ``cli.commands`` exposes:
  * ``register(subparsers)``  — adds its parser + ``set_defaults(func=...)``
  * ``handle(args, settings, logger) -> int`` (async by default, or sync
    ``handle(args, settings)`` if it declares ``IS_ASYNC = False``)

Filename ``<name>.py`` maps to the CLI subcommand 1:1, with underscores
becoming dashes (``probe_reader`` → ``probe-reader``).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib

from mteam_cli.core.config import Settings
from mteam_cli.core.logging_utils import configure_logging

_COMMAND_MODULES = (
    # automation / diagnostics
    "doctor",
    "login",
    "run",
    "schedule",
    "inspect",
    # data queries (API key)
    "profile",
    "search",
    "detail",
    "seeding",
    "hnr",
    "messages",
    "notices",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mteam-cli",
        description="M-Team CLI — 保活自动化 + AI 友好的数据查询。",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for modname in _COMMAND_MODULES:
        mod = importlib.import_module(f"mteam_cli.cli.commands.{modname}")
        mod.register(sub)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    settings = Settings.from_env()
    settings.ensure_directories()

    # ``doctor`` is intentionally sync — it must run even when playwright /
    # pyotp / etc. are missing, so it can diagnose them.
    if getattr(args, "is_async", True) is False:
        raise SystemExit(args.func(args, settings))

    logger, log_path = configure_logging(settings.log_dir)
    logger.info("Using log file %s", log_path)
    raise SystemExit(asyncio.run(args.func(args, settings, logger)))


if __name__ == "__main__":
    main()
