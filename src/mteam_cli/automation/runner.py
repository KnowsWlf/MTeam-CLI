"""High-level keep-alive tick orchestration (multi-account, no QR).

Single source of truth shared by:
  * ``cli.commands.run``       — manual one-shot
  * ``cli.commands.schedule``  — daily scheduled tick (one job per account)

Per account: build that account's own notifier hub, open a fresh browser, run
the proven login flow, and fire a CHECKIN_DONE / CHECKIN_FAILED notification
through the account's own channels. Failures are isolated — one account never
blocks or crashes the others.
"""

from __future__ import annotations

import logging

from mteam_cli.automation.login import perform_login
from mteam_cli.cli._browser import browser_session_ctx
from mteam_cli.core.config import Account, Settings
from mteam_cli.core.models import CheckinResult
from mteam_cli.notify import Notification, NotificationEvent, build_notifier_hub

CHECKIN_FAILED_EXIT_CODE = 1


async def run_one_account_tick(
    account: Account,
    settings: Settings,
    logger: logging.Logger,
) -> CheckinResult:
    """Run one account's keep-alive login end-to-end and notify the outcome."""
    if not account.can_keepalive:
        logger.warning("[%s] 缺少保活凭证，跳过", account.username)
        return CheckinResult(username=account.username, ok=False, skipped=True)

    hub = build_notifier_hub(account, settings, logger)
    try:
        async with browser_session_ctx(settings, logger) as ctx:
            result = await perform_login(ctx.session, account, settings, logger)
    except Exception as exc:  # noqa: BLE001 — isolate per account
        logger.exception("[%s] 保活过程崩溃", account.username)
        result = CheckinResult(username=account.username, ok=False, error=str(exc))

    event = NotificationEvent.CHECKIN_DONE if result.ok else NotificationEvent.CHECKIN_FAILED
    title = f"[{account.username}] 签到{'成功' if result.ok else '失败'}"
    await hub.notify(
        Notification(
            event=event,
            title=title,
            body=result.profile_text if result.ok else (result.error or "登录失败"),
        )
    )
    return result


async def run_all_accounts(
    settings: Settings,
    logger: logging.Logger,
    only: str | None = None,
) -> int:
    """Run every keep-alive-capable account (or just ``only``); worst exit code."""
    targets = [settings.resolve_account(only)] if only else list(settings.accounts)
    keepalive_targets = [a for a in targets if a.can_keepalive]

    if only and not keepalive_targets:
        from mteam_cli.cli._account import require_keepalive

        require_keepalive(targets[0])

    if not keepalive_targets:
        logger.warning("没有可保活的账户（需 user+pass+totp）。")
        return 0

    worst = 0
    for acct in keepalive_targets:
        try:
            result = await run_one_account_tick(acct, settings, logger)
            if not result.ok and not result.skipped:
                worst = CHECKIN_FAILED_EXIT_CODE
        except Exception:  # noqa: BLE001 — never let one account stop the rest
            logger.exception("[%s] tick 异常，继续下一个账户", acct.username)
            worst = CHECKIN_FAILED_EXIT_CODE
    return worst
