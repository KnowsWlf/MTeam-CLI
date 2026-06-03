"""Hit-and-run (H&R) / crime records for a member.

This endpoint rejects the API key (無許可權) — it needs the web session JWT.
We reuse the token persisted by ``mteam-cli login``/``run`` (localStorage
snapshot). Run login first if there is no session yet.
"""

from __future__ import annotations

import argparse
import logging

from mteam_cli.api import get_hnr
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
        "hnr", help="H&R（Hit and Run）记录。注意：M-Team 对该端点启用请求签名，CLI 不支持（网页端专用）。"
    )
    p.add_argument("--uid", default=None, help="查看指定用户（默认：自己）。")
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

    uid = args.uid or session.uid
    if not uid:
        notice("无法确定 uid（会话未携带，且未指定 --uid）。")
        return 1

    data = await fetch(
        get_hnr(
            uid,
            base_url=settings.api_base_url,
            auth_token=session.auth_token,
            did=session.did,
            visitorid=session.visitorid,
        )
    )
    if maybe_raw(args, data):
        return 0

    rows = as_list(data)
    if not rows:
        notice("无 H&R 记录。")
        return 0
    if args.output_format in ("table", "md") and has_nested_values(rows):
        notice("提示：响应含嵌套字段，表格可能不易读，建议加 --raw 查看完整 JSON。")
    emit_rows(rows, auto_fields(rows), fmt=args.output_format)
    return 0
