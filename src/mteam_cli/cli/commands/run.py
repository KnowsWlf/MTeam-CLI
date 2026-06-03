"""Execute one keep-alive tick immediately (all accounts, or one)."""

from __future__ import annotations

import argparse
import logging

from mteam_cli.automation.runner import run_all_accounts
from mteam_cli.cli._account import add_account_arg
from mteam_cli.core.config import Settings


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "run", help="立即执行一次保活（默认所有账户，--account 限定单个）。"
    )
    add_account_arg(p)
    p.set_defaults(func=handle)


async def handle(
    args: argparse.Namespace, settings: Settings, logger: logging.Logger
) -> int:
    return await run_all_accounts(settings, logger, only=args.account)
