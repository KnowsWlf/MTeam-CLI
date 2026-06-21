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

# 内置「类型 → 质量信号」映射：这两类有 IMDB 评分，用评分阈值；
# 其余类型（music/adult/…）没有 IMDB，改用 status.seeders（做种数=热度）阈值。
# 已对生产 api.m-team.cc 实测：music 条目 imdbRating/doubanRating 恒为 None，
# 而 status.seeders 有值。adult 同源（需账户开启成人浏览权限才有结果）。
_IMDB_TYPES = {"movie", "tvshow"}


def _parse_float(value: Any) -> float | None:
    """把评分字段转 float；空/非数字 → None。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    """把做种数等字段转 int；空/非数字 → None。M-Team 返回的是字符串数字。"""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
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


def _shape(
    t: dict[str, Any], *, mode: str, signal_kind: str, score: float | int
) -> dict[str, Any]:
    """把一条 search 结果整形为 digest 行。

    ``signal_kind`` ∈ {"imdb","seeders"}，``score`` 是该信号的数值（排序键）。
    行内同时保留 imdb 与 seeders 两个展示字段（没有则 "-"），便于 --raw 消费。
    """
    imdb = _parse_float(t.get("imdbRating"))
    seeders = _parse_int((t.get("status") or {}).get("seeders"))
    return {
        "id": t.get("id"),
        "title": t.get("smallDescr") or t.get("name"),
        "type": TYPE_LABELS.get(mode, mode),
        "imdb": imdb if imdb is not None else "-",
        "seeders": seeders if seeders is not None else "-",
        "douban": t.get("doubanRating") or "-",
        "size": naturalsize(t.get("size")),
        "createdDate": t.get("createdDate"),
        "signal_kind": signal_kind,
        "score": score,
    }


async def fetch_high_score_digest(
    api_key: str,
    *,
    base_url: str,
    min_imdb: float,
    types: list[str],
    hours: int,
    limit: int,
    min_seeders: int = 0,
    now: str | None = None,
) -> list[dict[str, Any]]:
    """拉取各类型最新结果，按类型对应的质量信号 + 发布时间窗过滤，降序截断。

    内置映射（``_IMDB_TYPES``）决定每个类型用哪种信号：
      * movie/tvshow → ``imdbRating ≥ min_imdb``
      * 其余（music/adult/…）→ ``status.seeders ≥ min_seeders``

    两种信号尺度不可比（imdb 0–10 vs seeders 数百），故**分桶**：imdb 组各自
    按 imdb 降序在前，seeders 组按 seeders 降序在后，再整体截断 ``limit``。
    纯影视配置时行为与旧版完全一致（跨类目按 imdb 排）。

    ``now`` 仅供测试注入。空关键词取各类目最新——已对生产 api.m-team.cc 实测。
    """
    imdb_rows: list[dict[str, Any]] = []
    seeders_rows: list[dict[str, Any]] = []
    for mode in types:
        data = await search_torrents(
            api_key, "", base_url=base_url, mode=mode, page_size=100
        )
        is_imdb = mode in _IMDB_TYPES
        for t in as_list(data):
            age = _age_hours(t.get("createdDate"), now=now)
            if age is not None and age > hours:
                continue
            if is_imdb:
                imdb = _parse_float(t.get("imdbRating"))
                if imdb is None or imdb < min_imdb:
                    continue
                imdb_rows.append(_shape(t, mode=mode, signal_kind="imdb", score=imdb))
            else:
                seeders = _parse_int((t.get("status") or {}).get("seeders"))
                if seeders is None or seeders < min_seeders:
                    continue
                seeders_rows.append(
                    _shape(t, mode=mode, signal_kind="seeders", score=seeders)
                )
    imdb_rows.sort(key=lambda r: r["score"], reverse=True)
    seeders_rows.sort(key=lambda r: r["score"], reverse=True)
    return (imdb_rows + seeders_rows)[:limit]


def format_digest(rows: list[dict[str, Any]], *, min_imdb: float | None = None) -> str:
    """生成签到通知尾部的 digest 文本片段；空结果返回空串（整段省略）。

    每行按其信号给标记：imdb 直接显示分数，seeders 加 🌱 前缀（做种数=热度）。
    """
    if not rows:
        return ""
    lines = ["📽 今日新片精选"]
    for r in rows:
        score = r.get("score", r.get("imdb"))
        if r.get("signal_kind") == "seeders":
            tag = f"🌱{score}"
        else:
            tag = f"{float(score):g}"
        lines.append(f"• [{tag}] {r['title']} ({r['type']})")
    return "\n".join(lines)
