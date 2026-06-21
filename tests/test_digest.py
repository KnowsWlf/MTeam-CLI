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
    row = _shape(t, mode="movie", signal_kind="imdb", score=9.1)
    assert row["id"] == "123"
    assert row["title"] == "某电影名"          # smallDescr 优先
    assert row["type"] == "电影"
    assert row["imdb"] == 9.1
    assert row["score"] == 9.1
    assert row["signal_kind"] == "imdb"
    assert row["douban"] == "8.8"
    assert row["size"] == "1.0 GiB"           # humanize binary
    assert row["createdDate"] == "2026-06-05 10:00:00"


def test_shape_falls_back_to_name():
    t = {"id": "1", "name": "Fallback", "imdbRating": "8.0"}
    row = _shape(t, mode="tvshow", signal_kind="imdb", score=8.0)
    assert row["title"] == "Fallback"
    assert row["type"] == "电视剧"


def test_shape_seeders_extracts_from_status():
    t = {
        "id": "9", "smallDescr": "某专辑", "name": "Album",
        "status": {"seeders": "326"},
        "createdDate": "2026-06-05 10:00:00",
    }
    row = _shape(t, mode="music", signal_kind="seeders", score=326)
    assert row["title"] == "某专辑"
    assert row["type"] == "音乐"
    assert row["seeders"] == 326
    assert row["score"] == 326
    assert row["signal_kind"] == "seeders"
    assert row["imdb"] == "-"          # music 无 imdb


import asyncio
import mteam_cli.api.digest as digest_mod


def _parse_int_check():
    from mteam_cli.api.digest import _parse_int
    assert _parse_int("326") == 326
    assert _parse_int(None) is None
    assert _parse_int("") is None
    assert _parse_int("x") is None


def test_parse_int():
    _parse_int_check()


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


def test_fetch_seeders_type_filters_by_seeders(monkeypatch):
    """music：按 status.seeders ≥ min_seeders 过滤，imdb 阈值不参与。"""
    by_mode = {"music": [
        {"id": "m1", "name": "热门", "status": {"seeders": "300"}, "createdDate": "2026-06-05 10:00:00"},
        {"id": "m2", "name": "冷门", "status": {"seeders": "5"}, "createdDate": "2026-06-05 10:00:00"},
        {"id": "m3", "name": "无status", "createdDate": "2026-06-05 10:00:00"},
    ]}
    monkeypatch.setattr(digest_mod, "search_torrents", _fake_search_factory(by_mode))
    rows = asyncio.run(
        digest_mod.fetch_high_score_digest(
            "KEY", base_url="B", min_imdb=8.0, types=["music"],
            hours=24, limit=10, min_seeders=30, now="2026-06-05 12:00:00",
        )
    )
    assert [r["id"] for r in rows] == ["m1"]  # 仅 seeders≥30
    assert rows[0]["signal_kind"] == "seeders"
    assert rows[0]["seeders"] == 300


def test_fetch_mixed_types_bucket_order(monkeypatch):
    """混合 movie+music：imdb 组（按 imdb 降序）在前，seeders 组（按 seeders 降序）在后。"""
    by_mode = {
        "movie": [
            {"id": "v1", "name": "V1", "imdbRating": "8.2", "createdDate": "2026-06-05 11:00:00"},
            {"id": "v2", "name": "V2", "imdbRating": "9.0", "createdDate": "2026-06-05 11:00:00"},
        ],
        "music": [
            {"id": "s1", "name": "S1", "status": {"seeders": "50"}, "createdDate": "2026-06-05 11:00:00"},
            {"id": "s2", "name": "S2", "status": {"seeders": "200"}, "createdDate": "2026-06-05 11:00:00"},
        ],
    }
    monkeypatch.setattr(digest_mod, "search_torrents", _fake_search_factory(by_mode))
    rows = asyncio.run(
        digest_mod.fetch_high_score_digest(
            "KEY", base_url="B", min_imdb=8.0, types=["movie", "music"],
            hours=24, limit=10, min_seeders=30, now="2026-06-05 12:00:00",
        )
    )
    # imdb 桶降序(v2>v1) 在前，seeders 桶降序(s2>s1) 在后——seeders(大数)不会挤掉 imdb
    assert [r["id"] for r in rows] == ["v2", "v1", "s2", "s1"]


from mteam_cli.api.digest import format_digest


def test_format_digest_empty_returns_blank():
    # 空结果整段省略
    assert format_digest([], min_imdb=8.0) == ""


def test_format_digest_lists_items():
    rows = [
        {"title": "片A", "type": "电影", "imdb": 9.3, "score": 9.3, "signal_kind": "imdb"},
        {"title": "剧B", "type": "电视剧", "imdb": 8.5, "score": 8.5, "signal_kind": "imdb"},
    ]
    out = format_digest(rows, min_imdb=8.0)
    assert "今日新片精选" in out
    assert "[9.3] 片A (电影)" in out
    assert "[8.5] 剧B (电视剧)" in out


def test_format_digest_seeders_row_uses_seedling_tag():
    rows = [{"title": "专辑C", "type": "音乐", "seeders": 326, "score": 326, "signal_kind": "seeders"}]
    out = format_digest(rows)
    assert "[🌱326] 专辑C (音乐)" in out
