from mteam_cli.api.digest import _parse_float, _age_hours


def test_parse_float_valid():
    assert _parse_float("8.5") == 8.5
    assert _parse_float(9) == 9.0


def test_parse_float_empty_or_bad():
    assert _parse_float("") is None
    assert _parse_float(None) is None
    assert _parse_float("N/A") is None


def test_age_hours_recent():
    # 距离 reference 2 小时
    age = _age_hours("2026-06-05 10:00:00", now="2026-06-05 12:00:00")
    assert age == 2.0


def test_age_hours_unparseable_returns_none():
    # 解析失败返回 None（调用方据此保留条目，宁多勿漏）
    assert _age_hours("not-a-date", now="2026-06-05 12:00:00") is None


from mteam_cli.api.digest import _shape


def test_shape_extracts_fields():
    t = {
        "id": "123",
        "smallDescr": "某电影名",
        "name": "Movie.Name.2026",
        "imdbRating": "9.1",
        "doubanRating": "8.8",
        "size": "1073741824",
        "createdDate": "2026-06-05 10:00:00",
    }
    row = _shape(t, mode="movie", imdb=9.1)
    assert row["id"] == "123"
    assert row["title"] == "某电影名"          # smallDescr 优先
    assert row["type"] == "电影"
    assert row["imdb"] == 9.1
    assert row["douban"] == "8.8"
    assert row["size"] == "1.0 GiB"           # humanize binary
    assert row["createdDate"] == "2026-06-05 10:00:00"


def test_shape_falls_back_to_name():
    t = {"id": "1", "name": "Fallback", "imdbRating": "8.0"}
    row = _shape(t, mode="tvshow", imdb=8.0)
    assert row["title"] == "Fallback"
    assert row["type"] == "电视剧"


import asyncio
import mteam_cli.api.digest as digest_mod


def _fake_search_factory(by_mode):
    async def _fake(api_key, keyword, *, base_url, mode, page_number=1, page_size=20):
        return {"data": by_mode.get(mode, [])}
    return _fake


def test_fetch_filters_by_imdb_and_time(monkeypatch):
    by_mode = {
        "movie": [
            {"id": "1", "name": "高分新片", "imdbRating": "8.5", "createdDate": "2026-06-05 10:00:00"},
            {"id": "2", "name": "低分新片", "imdbRating": "6.0", "createdDate": "2026-06-05 10:00:00"},
            {"id": "3", "name": "高分旧片", "imdbRating": "9.0", "createdDate": "2026-06-01 10:00:00"},
            {"id": "4", "name": "无评分", "imdbRating": "", "createdDate": "2026-06-05 10:00:00"},
        ],
    }
    monkeypatch.setattr(digest_mod, "search_torrents", _fake_search_factory(by_mode))
    rows = asyncio.run(
        digest_mod.fetch_high_score_digest(
            "KEY", base_url="B", min_imdb=8.0, types=["movie"],
            hours=24, limit=10, now="2026-06-05 12:00:00",
        )
    )
    ids = [r["id"] for r in rows]
    assert ids == ["1"]  # 只有 id=1 同时满足 IMDB≥8 且 24h 内


def test_fetch_sorts_desc_and_limits(monkeypatch):
    by_mode = {
        "movie": [
            {"id": "a", "name": "A", "imdbRating": "8.1", "createdDate": "2026-06-05 11:00:00"},
            {"id": "b", "name": "B", "imdbRating": "9.5", "createdDate": "2026-06-05 11:00:00"},
            {"id": "c", "name": "C", "imdbRating": "8.7", "createdDate": "2026-06-05 11:00:00"},
        ],
    }
    monkeypatch.setattr(digest_mod, "search_torrents", _fake_search_factory(by_mode))
    rows = asyncio.run(
        digest_mod.fetch_high_score_digest(
            "KEY", base_url="B", min_imdb=8.0, types=["movie"],
            hours=24, limit=2, now="2026-06-05 12:00:00",
        )
    )
    assert [r["id"] for r in rows] == ["b", "c"]  # 降序后截断到 2


def test_fetch_unparseable_date_kept(monkeypatch):
    by_mode = {"movie": [
        {"id": "x", "name": "X", "imdbRating": "8.2", "createdDate": "bad-date"},
    ]}
    monkeypatch.setattr(digest_mod, "search_torrents", _fake_search_factory(by_mode))
    rows = asyncio.run(
        digest_mod.fetch_high_score_digest(
            "KEY", base_url="B", min_imdb=8.0, types=["movie"],
            hours=24, limit=10, now="2026-06-05 12:00:00",
        )
    )
    assert [r["id"] for r in rows] == ["x"]  # 日期解析失败保留


from mteam_cli.api.digest import format_digest


def test_format_digest_empty_returns_blank():
    # 空结果整段省略
    assert format_digest([], min_imdb=8.0) == ""


def test_format_digest_lists_items():
    rows = [
        {"title": "片A", "type": "电影", "imdb": 9.3},
        {"title": "剧B", "type": "电视剧", "imdb": 8.5},
    ]
    out = format_digest(rows, min_imdb=8.0)
    assert "IMDB≥8.0" in out
    assert "[9.3] 片A (电影)" in out
    assert "[8.5] 剧B (电视剧)" in out
