"""高分新片摘要：复用 search API，本地按 IMDB + 发布时间过滤。

纯 HTTP（经由 api_post / search_torrents），不依赖 Playwright。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mteam_cli.api.humanize import naturalsize
from mteam_cli.api.public import as_list, search_torrents

# search mode → 中文展示名
TYPE_LABELS = {
    "movie": "电影",
    "tvshow": "电视剧",
    "music": "音乐",
    "adult": "成人",
    "waterfall": "瀑布流",
    "rss": "RSS",
    "rankings": "排行",
    "all": "全部",
    "normal": "综合",
}

_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def _parse_float(value: Any) -> float | None:
    """把评分字段转 float；空/非数字 → None。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _age_hours(created: Any, *, now: str | None = None) -> float | None:
    """资源发布距今小时数；解析失败 → None（调用方据此保留，宁多勿漏）。

    ``now`` 仅供测试注入；生产传 None 用当前时间。
    """
    if not created:
        return None
    try:
        dt = datetime.strptime(str(created), _DATE_FMT)
    except (TypeError, ValueError):
        return None
    ref = datetime.strptime(now, _DATE_FMT) if now else datetime.now()
    return (ref - dt).total_seconds() / 3600.0


def _shape(t: dict[str, Any], *, mode: str, imdb: float) -> dict[str, Any]:
    """把一条 search 结果整形为 digest 行。"""
    return {
        "id": t.get("id"),
        "title": t.get("smallDescr") or t.get("name"),
        "type": TYPE_LABELS.get(mode, mode),
        "imdb": imdb,
        "douban": t.get("doubanRating") or "-",
        "size": naturalsize(t.get("size")),
        "createdDate": t.get("createdDate"),
    }


async def fetch_high_score_digest(
    api_key: str,
    *,
    base_url: str,
    min_imdb: float,
    types: list[str],
    hours: int,
    limit: int,
    now: str | None = None,
) -> list[dict[str, Any]]:
    """拉取各类型最新结果，按 IMDB 阈值 + 发布时间窗过滤，降序截断。

    ``now`` 仅供测试注入。空关键词 + mode=movie/tvshow 取该类目最新——已对生产
    api.m-team.cc 实测确认可用（返回最新影视，按发布时间倒序）。
    """
    rows: list[dict[str, Any]] = []
    for mode in types:
        data = await search_torrents(
            api_key, "", base_url=base_url, mode=mode, page_size=100
        )
        for t in as_list(data):
            imdb = _parse_float(t.get("imdbRating"))
            if imdb is None or imdb < min_imdb:
                continue
            age = _age_hours(t.get("createdDate"), now=now)
            if age is not None and age > hours:
                continue
            rows.append(_shape(t, mode=mode, imdb=imdb))
    rows.sort(key=lambda r: r["imdb"], reverse=True)
    return rows[:limit]


def format_digest(rows: list[dict[str, Any]], *, min_imdb: float) -> str:
    """生成签到通知尾部的 digest 文本片段；空结果返回空串（整段省略）。"""
    if not rows:
        return ""
    lines = [f"📽 今日高分新片 (IMDB≥{min_imdb})"]
    for r in rows:
        lines.append(f"• [{r['imdb']:g}] {r['title']} ({r['type']})")
    return "\n".join(lines)
