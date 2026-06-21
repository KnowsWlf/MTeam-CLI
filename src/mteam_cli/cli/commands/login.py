"""Manual one-shot keep-alive login for one account."""

from __future__ import annotations

import argparse
import logging

from mteam_cli.automation.login import perform_login
from mteam_cli.cli._account import add_account_arg, require_keepalive, resolve_account_or_exit
from mteam_cli.core.browser_ctx import browser_session_ctx
from mteam_cli.core.config import Settings
from mteam_cli.notify import Notification, NotificationEvent, build_notifier_hub


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("login", help="对某个账户执行一次保活登录（账号密码+TOTP）。")
    add_account_arg(p)
    p.set_defaults(func=handle)


async def handle(
    args: argparse.Namespace, settings: Settings, logger: logging.Logger
) -> int:
    account = resolve_account_or_exit(args, settings)
    require_keepalive(account)
    hub = build_notifier_hub(account, settings, logger)

    async with browser_session_ctx(settings, logger) as ctx:
        result = await perform_login(ctx.session, account, settings, logger)

    event = NotificationEvent.CHECKIN_DONE if result.ok else NotificationEvent.CHECKIN_FAILED
    title = f"[{account.username}] 登录{'成功' if result.ok else '失败'}"
    await hub.notify(
        Notification(
            event=event,
            title=title,
            body=result.profile_text if result.ok else result.error,
        )
    )

    if result.ok:
        print(f"登录成功：{account.username}")
        print(result.profile_text)
        return 0
    print(f"登录失败：{account.username} — {result.error}")
    return 1
