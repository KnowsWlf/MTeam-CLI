"""Health check — synchronous, no playwright/pyotp/api imports.

Stays import-light so it can diagnose a broken environment.
"""

from __future__ import annotations

import argparse

from mteam_cli.core.config import Settings

IS_ASYNC = False


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "doctor", help="自检：账户配置、通知配置、路径、调度参数。"
    )
    p.set_defaults(func=handle, is_async=False)


def handle(args: argparse.Namespace, settings: Settings) -> int:
    checks: list[tuple[str, bool, str]] = [
        ("base_url", bool(settings.base_url), settings.base_url),
        ("api_base_url", bool(settings.api_base_url), settings.api_base_url),
        ("auth_dir", settings.auth_dir.exists(), str(settings.auth_dir)),
        ("log_dir", settings.log_dir.exists(), str(settings.log_dir)),
        ("artifact_dir", settings.artifact_dir.exists(), str(settings.artifact_dir)),
        ("accounts", len(settings.accounts) > 0, f"{len(settings.accounts)} 个"),
        ("schedule_window", _valid_window(settings.schedule_window), settings.schedule_window),
        (
            "schedule_pre_delay_range",
            _valid_range(settings.schedule_pre_delay_range),
            settings.schedule_pre_delay_range,
        ),
    ]

    all_ok = True
    for name, ok, value in checks:
        status = "OK" if ok else "MISSING"
        if not ok:
            all_ok = False
        print(f"{status:<8} {name:<26} {value}")

    # Per-account capability + notify matrix.
    print()
    print("账户（keep-alive 需 user+pass+totp；query 需 api_key）：")
    if not settings.accounts:
        print("  (无账户)")
    for acct in settings.accounts:
        cap_k = "保活" if acct.can_keepalive else "—"
        cap_q = "查询" if acct.can_query else "—"
        storage = acct.storage_path(settings.auth_dir)
        seen = "已登录态" if storage.exists() else "未登录"
        channels = []
        if acct.has_telegram:
            channels.append("TG")
        if acct.has_smtp(settings):
            channels.append("SMTP")
        if acct.has_feishu:
            channels.append("飞书")
        ch = "+".join(channels) if channels else "无通知"
        print(f"  - {acct.username:<20} [{cap_k}/{cap_q}]  通知:{ch:<12} {seen}")
        if not acct.can_keepalive and not acct.can_query:
            print(f"    ⚠ {acct.username} 既不能保活也不能查询，请补全凭证。")
            all_ok = False
        if acct.can_keepalive and not channels:
            print(f"    ⚠ {acct.username} 可保活但无任何通知渠道，结果只记日志。")

    # Global SMTP server status.
    print()
    print("SMTP 服务（全局，收件人按账户 NOTIFY_SMTP_TO_<n> / NOTIFY_EMAIL_<n>）：")
    if settings.smtp_host:
        print(f"  {settings.smtp_host}:{settings.smtp_port}  from={settings.smtp_from}  tls={settings.smtp_use_tls}")
    else:
        print("  (未配置)")

    return 0 if all_ok else 1


def _valid_window(spec: str) -> bool:
    try:
        low, high = spec.split("-", 1)
        for hm in (low.strip(), high.strip()):
            h, m = hm.split(":", 1)
            if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                return False
        return True
    except (ValueError, IndexError):
        return False


def _valid_range(spec: str) -> bool:
    try:
        a, b = spec.split("-", 1)
        return int(a) >= 0 and int(b) >= int(a)
    except (ValueError, IndexError):
        return False
