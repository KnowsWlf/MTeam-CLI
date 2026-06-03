"""Inbox / private messages.

This endpoint rejects the API key (401 Full authentication required) — it needs
the web session JWT. We reuse the token persisted by ``mteam-cli login``/``run``
(localStorage snapshot). Run login first if there is no session yet.
"""

from __future__ import annotations

import argparse
import logging

from mteam_cli.api import get_messages
from mteam_cli.api.public import as_list
from mteam_cli.cli._account import (
    add_account_arg,
    resolve_account_or_exit,
    resolve_session_or_exit,
)
from mteam_cli.cli._emit import (
    add_format_arg,
    add_raw_arg,
    auto_fields,
    emit_rows,
    has_nested_values,
    notice,
)
from mteam_cli.cli._query import fetch, maybe_raw, run
from mteam_cli.core.config import Settings


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "messages", help="站内信（收件箱）。注意：M-Team 对该端点启用请求签名，CLI 不支持（网页端专用）。"
    )
    p.add_argument("-n", "--limit", type=int, default=20, help="每页数量 (默认: 20)")
    p.add_argument("--page", type=int, default=1, help="页码 (默认: 1)")
    p.add_argument("--box", type=int, default=None, help="信箱 ID（默认：全部）。")
    add_account_arg(p)
    add_format_arg(p)
    add_raw_arg(p)
    p.set_defaults(func=handle)


async def handle(
    args: argparse.Namespace, settings: Settings, logger: logging.Logger
) -> int:
    return await run(_run(args, settings))


async def _run(args: argparse.Namespace, settings: Settings) -> int:
    account = resolve_account_or_exit(args, settings)
    session = resolve_session_or_exit(account, settings)

    data = await fetch(
        get_messages(
            base_url=settings.api_base_url,
            auth_token=session.auth_token,
            did=session.did,
            visitorid=session.visitorid,
            box_id=args.box,
            page_number=args.page,
            page_size=args.limit,
        )
    )
    if maybe_raw(args, data):
        return 0

    rows = as_list(data)
    if not rows:
        notice("无站内信。")
        return 0
    if args.output_format in ("table", "md") and has_nested_values(rows):
        notice("提示：响应含嵌套字段，表格可能不易读，建议加 --raw 查看完整 JSON。")
    emit_rows(rows, auto_fields(rows), fmt=args.output_format)
    return 0
