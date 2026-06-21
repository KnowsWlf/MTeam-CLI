"""Shared ``--account`` plumbing for every command.

Data commands target one account (``--account``, defaulting to the first
configured one). ``run``/``schedule`` ignore it and cover all accounts.
"""

from __future__ import annotations

import argparse

from mteam_cli.core.config import Account, Settings


def add_account_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--account",
        dest="account",
        default=None,
        metavar="USERNAME",
        help="目标账户用户名（默认：第一个已配置账户）。",
    )


def resolve_account_or_exit(args: argparse.Namespace, settings: Settings) -> Account:
    """Resolve the selected account or exit with a clear message."""
    return settings.resolve_account(getattr(args, "account", None))


def require_query(account: Account) -> None:
    """Guard: a data command needs this account's api_key."""
    account.ensure_query()


def require_keepalive(account: Account) -> None:
    """Guard: a keep-alive command needs username+password+totp."""
    account.ensure_keepalive()


def resolve_session_or_exit(account: Account, settings: Settings):
    """Load the web-session JWT for ``account``, or raise QueryExit(1).

    Used by the session-only data commands (``hnr``/``messages``) that the API
    key can't reach. Returns a ``WebSession``. Writes a stderr hint and unwinds
    via ``QueryExit`` when no snapshot exists yet.
    """
    from mteam_cli.api import load_session
    from mteam_cli.cli._emit import notice
    from mteam_cli.cli._query import QueryExit

    session = load_session(account.storage_path(settings.auth_dir))
    if session is None:
        notice(
            f"该端点需要登录会话。请先运行 `mteam-cli login --account {account.username}`，"
            "再执行本命令。"
        )
        raise QueryExit(1)
    return session
