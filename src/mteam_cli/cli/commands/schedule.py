"""Long-running daily scheduler (all accounts) — the container default command."""

from __future__ import annotations

import argparse

from mteam_cli.automation.runner import run_one_account_tick
from mteam_cli.core.config import Account, Settings
from mteam_cli.scheduler.daily import DailyScheduler

IS_ASYNC = False


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "schedule", help="常驻：每天为每个账户在随机时刻自动保活（容器默认命令）。"
    )
    p.set_defaults(func=handle, is_async=False)


def handle(args: argparse.Namespace, settings: Settings) -> int:
    # ``schedule`` runs its own sync loop (the schedule library) and spawns a
    # fresh ``asyncio.run`` per tick, so it is declared sync (IS_ASYNC=False)
    # and builds its own logger. Notifier hubs are built per-account per tick.
    from mteam_cli.core.logging_utils import configure_logging

    logger, log_path = configure_logging(settings.log_dir)
    logger.info("Using log file %s", log_path)

    def tick_factory(account: Account):
        return run_one_account_tick(account, settings, logger)

    DailyScheduler(settings, logger, tick_factory).loop()
    return 0
