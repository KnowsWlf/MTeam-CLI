"""Build a per-account NotifierHub.

Each channel opts in via that account's own config. Telegram/Feishu are fully
per-account. SMTP shares a global server config (``Settings.smtp_*``) but the
recipient is per-account (``Account.smtp_to`` / ``NOTIFY_SMTP_TO_<n>``).
"""

from __future__ import annotations

import logging

from mteam_cli.core.config import Account, Settings
from mteam_cli.notify.base import Notifier, NotifierHub
from mteam_cli.notify.feishu import FeishuNotifier
from mteam_cli.notify.smtp import SMTPNotifier
from mteam_cli.notify.telegram import TelegramNotifier


def build_notifier_hub(
    account: Account,
    settings: Settings,
    logger: logging.Logger,
) -> NotifierHub:
    notifiers: list[Notifier] = []

    if account.has_telegram:
        notifiers.append(
            TelegramNotifier(
                token=account.telegram_token,
                chat_id=account.telegram_chat_id,
            )
        )

    if account.has_smtp(settings):
        recipients = [r.strip() for r in (account.smtp_to or "").split(",") if r.strip()]
        notifiers.append(
            SMTPNotifier(
                host=settings.smtp_host,
                port=settings.smtp_port,
                user=settings.smtp_user,
                password=settings.smtp_password,
                sender=settings.smtp_from,
                recipients=recipients,
                use_tls=settings.smtp_use_tls,
            )
        )

    if account.has_feishu:
        notifiers.append(FeishuNotifier(token=account.feishu_token))

    hub = NotifierHub(notifiers, logger)
    if notifiers:
        logger.info("[%s] Notifiers enabled: %s", account.username, ", ".join(hub.enabled_names))
    else:
        logger.info("[%s] 无通知渠道（设置该账户的 NOTIFY_*_<n> 以启用）", account.username)
    return hub
