"""高分新片摘要预览命令（API key）。"""

from __future__ import annotations

import argparse
import logging

from mteam_cli.api import fetch_high_score_digest
from mteam_cli.cli._account import add_account_arg, require_query, resolve_account_or_exit
from mteam_cli.cli._emit import Field, add_format_arg, add_raw_arg, emit_rows, notice
from mteam_cli.cli._query import fetch, maybe_raw, run
from mteam_cli.core.config import Settings

_FIELDS = [
    Field("rank", "#"),
    Field("id", "ID"),
    Field("title", "标题"),
    Field("type", "类型"),
    Field("imdb", "IMDB"),
    Field("douban", "豆瓣"),
    Field("size", "大小"),
    Field("createdDate", "发布时间"),
]


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("digest", help="预览当天高分新片（IMDB 高分影视）。")
    p.add_argument("--min-imdb", type=float, default=None, help="IMDB 评分下限（默认取全局配置）")
    p.add_argument("--types", default=None, help="资源类型，逗号分隔（默认取全局配置）")
    p.add_argument("--hours", type=int, default=None, help="发布时间窗（小时，默认取全局配置）")
    p.add_argument("-n", "--limit", type=int, default=None, help="最多条数（默认取全局配置）")
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

    min_imdb = args.min_imdb if args.min_imdb is not None else settings.digest_min_imdb
    types = (
        [t.strip() for t in args.types.split(",") if t.strip()]
        if args.types
        else settings.digest_types
    )
    hours = args.hours if args.hours is not None else settings.digest_hours
    limit = args.limit if args.limit is not None else settings.digest_limit

    rows = await fetch(
        fetch_high_score_digest(
            account.api_key,
            base_url=settings.api_base_url,
            min_imdb=min_imdb,
            types=types,
            hours=hours,
            limit=limit,
        )
    )
    # 与 search 不同：digest 是跨多次 search 的聚合+过滤，没有单一"原始 API
    # 响应"。--raw 输出过滤后的完整行（含表格精简掉的 douban/size/createdDate
    # 等全字段），对下游/AI 消费最有用。
    if maybe_raw(args, rows):
        return 0

    if not rows:
        notice(f"当天无 IMDB≥{min_imdb:g} 的新片。")
        return 0
    ranked = [{**r, "rank": i} for i, r in enumerate(rows, start=1)]
    emit_rows(ranked, _FIELDS, fmt=args.output_format)
    return 0
