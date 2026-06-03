"""Current seeding (default) or leeching torrents (API key).

Resolves the API key owner's own uid first (via profile), unless --uid is given.
Each row nests a ``torrent`` object + a ``peer`` object; we flatten the useful
fields into clean columns.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from mteam_cli.api import get_own_uid, get_peer_list
from mteam_cli.api import humanize as hz
from mteam_cli.api.public import as_list
from mteam_cli.cli._account import add_account_arg, require_query, resolve_account_or_exit
from mteam_cli.cli._emit import Field, add_format_arg, add_raw_arg, emit_rows, notice
from mteam_cli.cli._query import fetch, maybe_raw, run
from mteam_cli.core.config import Settings

_FIELDS = [
    Field("id", "ID"),
    Field("title", "标题"),
    Field("size", "大小"),
    Field("uploaded", "已传"),
    Field("downloaded", "已下"),
    Field("client", "客户端"),
    Field("lastAction", "最近活动"),
]


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("seeding", help="当前做种/下载列表。")
    p.add_argument("--leeching", action="store_true", help="改看正在下载（默认做种）。")
    p.add_argument("--uid", default=None, help="查看指定用户（默认：自己）。")
    p.add_argument("-n", "--limit", type=int, default=50, help="每页数量 (默认: 50)")
    p.add_argument("--page", type=int, default=1, help="页码 (默认: 1)")
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
    base = settings.api_base_url

    # getUserTorrentList requires a userid (probe-confirmed: 參數錯誤 without
    # it), so the default path costs one extra profile fetch to learn our own
    # uid. Pass --uid to skip it.
    uid = args.uid or await fetch(get_own_uid(account.api_key, base_url=base))
    data = await fetch(
        get_peer_list(
            account.api_key,
            uid,
            base_url=base,
            leeching=args.leeching,
            page_number=args.page,
            page_size=args.limit,
        )
    )
    if maybe_raw(args, data):
        return 0

    rows = [_shape(it) for it in as_list(data)]
    if not rows:
        notice("无下载中种子。" if args.leeching else "无做种中种子。")
        return 0
    emit_rows(rows, _FIELDS, fmt=args.output_format)
    return 0


def _shape(item: dict[str, Any]) -> dict[str, Any]:
    t = item.get("torrent") or {}
    p = item.get("peer") or {}
    return {
        "id": t.get("id"),
        "title": t.get("smallDescr") or t.get("name"),
        "size": hz.naturalsize(t.get("size")),
        "uploaded": hz.naturalsize(p.get("uploaded")),
        "downloaded": hz.naturalsize(p.get("downloaded")),
        "client": p.get("agent"),
        "lastAction": p.get("lastAction"),
    }
