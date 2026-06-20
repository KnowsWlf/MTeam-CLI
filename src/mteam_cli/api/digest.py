"""高分新片摘要：复用 search API，本地按 IMDB + 发布时间过滤。

纯 HTTP（经由 api_post / search_torrents），不依赖 Playwright。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
