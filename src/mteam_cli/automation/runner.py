"""High-level keep-alive tick orchestration (multi-account, no QR).

Single source of truth shared by:
  * ``cli.commands.run``       — manual one-shot
  * ``cli.commands.schedule``  — daily scheduled tick (one job per account)

Per account: build that account's own notifier hub, open a fresh browser, run
the proven login flow, optionally fetch that account's own high-score digest
(using its own api_key + its own resolved config), and fire a CHECKIN_DONE /
CHECKIN_FAILED notification through the account's own channels. Failures are
isolated — one account never blocks or crashes the others, and digest never
affects keep-alive.
"""

from __future__ import annotations

import logging

from mteam_cli.api import fetch_high_score_digest, format_digest
from mteam_cli.automation.login import perform_login
from mteam_cli.core.browser_ctx import browser_session_ctx
from mteam_cli.core.config import Account, DigestConfig, Settings
from mteam_cli.core.models import CheckinResult
from mteam_cli.notify import Notification, NotificationEvent, build_notifier_hub

CHECKIN_FAILED_EXIT_CODE = 1


async def run_one_account_tick(
    account: Account,
    settings: Settings,
    logger: logging.Logger,
) -> CheckinResult:
    """Run one account's keep-alive login end-to-end and notify the outcome.

    If the account opted into digest (and can query), fetch its own digest with
    its own api_key + resolved config and append it to the success body.
    """
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

    digest_text = ""
    if result.ok and account.digest_enabled:
        if account.can_query:
            cfg = account.resolved_digest_config(settings)
            digest_text = await _fetch_digest_for(account, cfg, settings, logger)
        else:
            logger.warning("[%s] digest 已开启但无 api_key，跳过", account.username)

    event = NotificationEvent.CHECKIN_DONE if result.ok else NotificationEvent.CHECKIN_FAILED
    title = f"[{account.username}] 签到{'成功' if result.ok else '失败'}"
    await hub.notify(
        Notification(
            event=event,
            title=title,
            body=_compose_body(result, digest_text),
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
        targets[0].ensure_keepalive()

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


def _compose_body(result: CheckinResult, digest_text: str) -> str:
    """签到通知正文：成功为 profile，有 digest 文本则拼接。

    digest 的开关判断在调用方（拉取阶段）已完成——这里只看是否有内容，
    无二次判断。
    """
    if not result.ok:
        return result.error or "登录失败"
    if digest_text:
        return f"{result.profile_text}\n\n{digest_text}"
    return result.profile_text


async def _fetch_digest_for(
    account: Account,
    cfg: DigestConfig,
    settings: Settings,
    logger: logging.Logger,
) -> str:
    """用本账户的 api_key + cfg 拉取并格式化它自己的高分新片摘要。

    任何失败只记日志、返回空串——digest 永不影响保活。
    """
    try:
        rows = await fetch_high_score_digest(
            account.api_key,
            base_url=settings.api_base_url,
            min_imdb=cfg.min_imdb,
            types=cfg.types,
            hours=cfg.hours,
            limit=cfg.limit,
        )
        logger.info(
            "[%s] digest: 命中 %d 条（min_imdb=%s, types=%s, hours=%d）",
            account.username, len(rows), cfg.min_imdb, ",".join(cfg.types), cfg.hours,
        )
        return format_digest(rows, min_imdb=cfg.min_imdb)
    except Exception:  # noqa: BLE001 — digest 失败绝不影响签到
        logger.exception("[%s] digest 拉取失败，本轮通知不含高分新片", account.username)
        return ""
