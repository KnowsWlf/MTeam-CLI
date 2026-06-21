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
    digest_text: str = "",
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

    if not digest_text and account.digest_enabled and result.ok:
        digest_text = await _maybe_fetch_digest([account], settings, logger)

    event = NotificationEvent.CHECKIN_DONE if result.ok else NotificationEvent.CHECKIN_FAILED
    title = f"[{account.username}] 签到{'成功' if result.ok else '失败'}"
    await hub.notify(
        Notification(
            event=event,
            title=title,
            body=_compose_body(result, account, digest_text),
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

    digest_text = await _maybe_fetch_digest(keepalive_targets, settings, logger)

    worst = 0
    for acct in keepalive_targets:
        try:
            result = await run_one_account_tick(acct, settings, logger, digest_text)
            if not result.ok and not result.skipped:
                worst = CHECKIN_FAILED_EXIT_CODE
        except Exception:  # noqa: BLE001 — never let one account stop the rest
            logger.exception("[%s] tick 异常，继续下一个账户", acct.username)
            worst = CHECKIN_FAILED_EXIT_CODE
    return worst


def _compose_body(result: CheckinResult, account: Account, digest_text: str) -> str:
    """签到通知正文：成功时为 profile；开了 digest 开关且有内容则拼接。"""
    if not result.ok:
        return result.error or "登录失败"
    body = result.profile_text
    if account.digest_enabled and digest_text:
        body = f"{body}\n\n{digest_text}"
    return body


async def _maybe_fetch_digest(
    targets: list[Account],
    settings: Settings,
    logger: logging.Logger,
) -> str:
    """若有账户开了 digest 开关，用第一个有 api_key 的账户拉一次并格式化。

    全站统一内容，只拉一次。任何失败只记日志、返回空串——绝不影响签到。
    """
    if not any(a.digest_enabled for a in targets):
        return ""
    fetcher = next((a for a in settings.accounts if a.can_query), None)
    if fetcher is None:
        logger.warning("digest 已开启但无可用 api_key 账户，跳过。")
        return ""
    try:
        from mteam_cli.api import fetch_high_score_digest, format_digest

        rows = await fetch_high_score_digest(
            fetcher.api_key,
            base_url=settings.api_base_url,
            min_imdb=settings.digest_min_imdb,
            types=settings.digest_types,
            hours=settings.digest_hours,
            limit=settings.digest_limit,
        )
        return format_digest(rows, min_imdb=settings.digest_min_imdb)
    except Exception:  # noqa: BLE001 — digest 失败绝不影响签到
        logger.exception("digest 拉取失败，本轮通知不含高分新片")
        return ""
