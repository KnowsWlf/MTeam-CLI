"""DigestConfig 值对象 + _coalesce 纯函数测试。

digest 配置的解析/继承/覆盖语义现由 test_config_toml.py 覆盖（TOML 构造）。
本文件只留与配置来源无关的纯函数单测。
"""

from mteam_cli.core.config import DigestConfig, _coalesce


def test_coalesce_prefers_first_non_none():
    assert _coalesce(5, 10) == 5
    assert _coalesce(None, 10) == 10


def test_coalesce_keeps_falsey_zero():
    # 0.0 / 0 是合法值，必须保留，不能当假值吞掉
    assert _coalesce(0.0, 8.0) == 0.0
    assert _coalesce(0, 10) == 0


def test_digest_config_is_frozen():
    cfg = DigestConfig(types=["movie"], min_imdb=8.0, hours=24, limit=10, min_seeders=30)
    assert cfg.types == ["movie"]
    assert cfg.min_imdb == 8.0
    try:
        cfg.min_imdb = 9.0
    except (AttributeError, Exception):
        return
    raise AssertionError("DigestConfig 应为 frozen")
