"""Site announcements / notices (API key).

⚠ PROBE-VERIFY: columns are auto-derived from the response until the endpoint
shape is confirmed.
"""

from __future__ import annotations

import argparse
import logging

from mteam_cli.api import get_notices
from mteam_cli.api.public import as_list
from mteam_cli.cli._account import add_account_arg, require_query, resolve_account_or_exit
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
    p = subparsers.add_parser("notices", help="站点公告 / 最新消息。")
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
    require_query(account)

    data = await fetch(get_notices(account.api_key, base_url=settings.api_base_url))
    if maybe_raw(args, data):
        return 0

    rows = as_list(data)
    if not rows:
        notice("无公告。")
        return 0
    if args.output_format in ("table", "md") and has_nested_values(rows):
        notice("提示：响应含嵌套字段，表格可能不易读，建议加 --raw 查看完整 JSON。")
    emit_rows(rows, auto_fields(rows), fmt=args.output_format)
    return 0
