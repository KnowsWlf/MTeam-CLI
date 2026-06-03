"""Search torrents by keyword (API key)."""

from __future__ import annotations

import argparse
import logging
from typing import Any

from mteam_cli.api import search_torrents
from mteam_cli.api import humanize as hz
from mteam_cli.api.public import as_list
from mteam_cli.cli._account import add_account_arg, require_query, resolve_account_or_exit
from mteam_cli.cli._emit import Field, add_format_arg, add_raw_arg, emit_rows, notice
from mteam_cli.cli._query import fetch, maybe_raw, run
from mteam_cli.core.config import Settings

_FIELDS = [
    Field("rank", "#"),
    Field("id", "ID"),
    Field("title", "标题"),
    Field("size", "大小"),
    Field("seeders", "做种"),
    Field("leechers", "下载"),
    Field("completed", "完成"),
    Field("discount", "优惠"),
    Field("imdb", "IMDB"),
    Field("douban", "豆瓣"),
]
_FOOTER = "提示：mteam-cli detail <ID> --dl-token 可生成下载链接。"


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("search", help="按关键词搜索种子。")
    p.add_argument("keyword", help="搜索关键词")
    p.add_argument("-n", "--limit", type=int, default=20, help="每页数量 (默认: 20)")
    p.add_argument("--page", type=int, default=1, help="页码 (默认: 1)")
    p.add_argument(
        "--mode",
        default="normal",
        help="模式: normal/adult/movie/music/tvshow/waterfall/rss/rankings/all (默认: normal)",
    )
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

    data = await fetch(
        search_torrents(
            account.api_key,
            args.keyword,
            base_url=settings.api_base_url,
            mode=args.mode,
            page_number=args.page,
            page_size=args.limit,
        )
    )
    if maybe_raw(args, data):
        return 0

    rows = [_shape(t, i) for i, t in enumerate(as_list(data), start=1)]
    if not rows:
        notice("未找到结果。")
        return 0
    emit_rows(rows, _FIELDS, fmt=args.output_format, footer=_FOOTER)
    return 0


def _shape(t: dict[str, Any], rank: int) -> dict[str, Any]:
    status = t.get("status") or {}
    return {
        "rank": rank,
        "id": t.get("id"),
        "title": t.get("smallDescr") or t.get("name"),
        "size": hz.naturalsize(t.get("size")),
        "seeders": status.get("seeders"),
        "leechers": status.get("leechers"),
        "completed": status.get("timesCompleted"),
        "discount": status.get("discount"),
        "imdb": t.get("imdbRating") or "-",
        "douban": t.get("doubanRating") or "-",
    }
