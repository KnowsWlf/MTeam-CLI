"""Torrent detail by id, with optional download-token generation (API key)."""

from __future__ import annotations

import argparse
import logging
from typing import Any

from mteam_cli.api import MTeamAPIError, gen_dl_token, get_torrent_detail
from mteam_cli.api import humanize as hz
from mteam_cli.cli._account import add_account_arg, require_query, resolve_account_or_exit
from mteam_cli.cli._emit import Field, add_format_arg, add_raw_arg, emit_record, notice
from mteam_cli.cli._query import fetch, maybe_raw, run
from mteam_cli.core.config import Settings

_FIELDS = [
    Field("id", "ID"),
    Field("name", "种子名"),
    Field("smallDescr", "标题"),
    Field("size", "大小"),
    Field("numfiles", "文件数"),
    Field("labels", "标签"),
    Field("seeders", "做种"),
    Field("leechers", "下载"),
    Field("completed", "完成次数"),
    Field("discount", "优惠"),
    Field("imdb", "IMDB"),
    Field("douban", "豆瓣"),
    Field("createdDate", "发布时间"),
    Field("downloadUrl", "下载链接"),
]


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("detail", help="查看某个种子的详情。")
    p.add_argument("id", help="种子 ID")
    p.add_argument(
        "--dl-token",
        action="store_true",
        help="同时生成下载链接（消耗下载权益，按需使用）。",
    )
    add_account_arg(p)
    add_format_arg(p)
    add_raw_arg(p)
    p.set_defaults(func=handle)


async def handle(
    args: argparse.Namespace, settings: Settings, logger: logging.Logger
) -> int:
    return await run(_run(args, settings, logger))


async def _run(
    args: argparse.Namespace, settings: Settings, logger: logging.Logger
) -> int:
    account = resolve_account_or_exit(args, settings)
    require_query(account)

    data = await fetch(
        get_torrent_detail(account.api_key, args.id, base_url=settings.api_base_url)
    )
    if not data:
        notice(f"未找到种子 {args.id}。")
        return 1
    if maybe_raw(args, data):
        return 0

    record = _shape(data)

    if args.dl_token:
        try:
            token = await gen_dl_token(
                account.api_key, args.id, base_url=settings.api_base_url
            )
            record["downloadUrl"] = token if isinstance(token, str) else (
                token.get("url") if isinstance(token, dict) else token
            )
        except MTeamAPIError as exc:
            logger.warning("生成下载链接失败: %s", exc)
            record["downloadUrl"] = f"(生成失败: {exc})"

    emit_record(record, _FIELDS, fmt=args.output_format)
    return 0


def _shape(t: dict[str, Any]) -> dict[str, Any]:
    status = t.get("status") or {}
    return {
        "id": t.get("id"),
        "name": t.get("name"),
        "smallDescr": t.get("smallDescr"),
        "size": hz.naturalsize(t.get("size")),
        "numfiles": t.get("numfiles"),
        "labels": ", ".join(t.get("labelsNew") or []) or "-",
        "seeders": status.get("seeders"),
        "leechers": status.get("leechers"),
        "completed": status.get("timesCompleted"),
        "discount": status.get("discount"),
        "imdb": t.get("imdbRating") or "-",
        "douban": t.get("doubanRating") or "-",
        "createdDate": t.get("createdDate"),
        "downloadUrl": "",
    }
