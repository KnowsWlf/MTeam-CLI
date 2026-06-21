import importlib

import mteam_cli.core.config as config_mod


def _reload_settings(monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    importlib.reload(config_mod)
    return config_mod.Settings.from_env()


def test_digest_enabled_defaults_false(monkeypatch):
    s = _reload_settings(monkeypatch, {
        "MTEAM_USERNAME_1": "u1", "MTEAM_API_KEY_1": "k1",
    })
    assert s.accounts[0].digest_enabled is False


def test_digest_enabled_per_account(monkeypatch):
    s = _reload_settings(monkeypatch, {
        "MTEAM_USERNAME_1": "u1", "MTEAM_API_KEY_1": "k1",
        "MTEAM_DIGEST_ENABLED_1": "true",
    })
    assert s.accounts[0].digest_enabled is True


def test_digest_global_defaults(monkeypatch):
    s = _reload_settings(monkeypatch, {
        "MTEAM_USERNAME_1": "u1", "MTEAM_API_KEY_1": "k1",
    })
    assert s.digest_min_imdb == 8.0
    assert s.digest_types == ["movie", "tvshow"]
    assert s.digest_hours == 24
    assert s.digest_limit == 10


def test_digest_global_overrides(monkeypatch):
    s = _reload_settings(monkeypatch, {
        "MTEAM_USERNAME_1": "u1", "MTEAM_API_KEY_1": "k1",
        "MTEAM_DIGEST_MIN_IMDB": "7.5",
        "MTEAM_DIGEST_TYPES": "movie",
        "MTEAM_DIGEST_HOURS": "48",
        "MTEAM_DIGEST_LIMIT": "5",
    })
    assert s.digest_min_imdb == 7.5
    assert s.digest_types == ["movie"]
    assert s.digest_hours == 48
    assert s.digest_limit == 5


from mteam_cli.core.config import DigestConfig, _coalesce


def test_coalesce_prefers_first_non_none():
    assert _coalesce(5, 10) == 5
    assert _coalesce(None, 10) == 10


def test_coalesce_keeps_falsey_zero():
    # 0.0 / 0 是合法值，必须保留，不能当假值吞掉
    assert _coalesce(0.0, 8.0) == 0.0
    assert _coalesce(0, 10) == 0


def test_digest_config_is_frozen():
    cfg = DigestConfig(types=["movie"], min_imdb=8.0, hours=24, limit=10)
    assert cfg.types == ["movie"]
    assert cfg.min_imdb == 8.0
    try:
        cfg.min_imdb = 9.0
    except (AttributeError, Exception):
        return
    raise AssertionError("DigestConfig 应为 frozen")


from mteam_cli.core.config import _suffixed_int, _suffixed_float


def test_suffixed_int_present(monkeypatch):
    monkeypatch.setenv("FOO_1", "48")
    assert _suffixed_int("FOO", 1) == 48


def test_suffixed_int_absent_or_blank(monkeypatch):
    monkeypatch.delenv("FOO_2", raising=False)
    assert _suffixed_int("FOO", 2) is None
    monkeypatch.setenv("FOO_3", "   ")
    assert _suffixed_int("FOO", 3) is None


def test_suffixed_float_present(monkeypatch):
    monkeypatch.setenv("BAR_1", "7.5")
    assert _suffixed_float("BAR", 1) == 7.5


def test_suffixed_float_absent(monkeypatch):
    monkeypatch.delenv("BAR_2", raising=False)
    assert _suffixed_float("BAR", 2) is None


def test_resolved_config_all_inherited(monkeypatch):
    s = _reload_settings(monkeypatch, {
        "MTEAM_USERNAME_1": "u1", "MTEAM_API_KEY_1": "k1",
    })
    cfg = s.accounts[0].resolved_digest_config(s)
    assert cfg.types == ["movie", "tvshow"]
    assert cfg.min_imdb == 8.0
    assert cfg.hours == 24
    assert cfg.limit == 10


def test_resolved_config_partial_override(monkeypatch):
    s = _reload_settings(monkeypatch, {
        "MTEAM_USERNAME_1": "u1", "MTEAM_API_KEY_1": "k1",
        "MTEAM_DIGEST_TYPES_1": "movie",
    })
    cfg = s.accounts[0].resolved_digest_config(s)
    assert cfg.types == ["movie"]       # 账户覆盖
    assert cfg.min_imdb == 8.0          # 继承全局
    assert cfg.hours == 24
    assert cfg.limit == 10


def test_resolved_config_full_override(monkeypatch):
    s = _reload_settings(monkeypatch, {
        "MTEAM_USERNAME_1": "u1", "MTEAM_API_KEY_1": "k1",
        "MTEAM_DIGEST_TYPES_1": "music,adult",
        "MTEAM_DIGEST_MIN_IMDB_1": "6.5",
        "MTEAM_DIGEST_HOURS_1": "72",
        "MTEAM_DIGEST_LIMIT_1": "3",
    })
    cfg = s.accounts[0].resolved_digest_config(s)
    assert cfg.types == ["music", "adult"]
    assert cfg.min_imdb == 6.5
    assert cfg.hours == 72
    assert cfg.limit == 3


def test_resolved_config_zero_imdb_not_swallowed(monkeypatch):
    s = _reload_settings(monkeypatch, {
        "MTEAM_USERNAME_1": "u1", "MTEAM_API_KEY_1": "k1",
        "MTEAM_DIGEST_MIN_IMDB_1": "0",
        "MTEAM_DIGEST_LIMIT_1": "0",
    })
    cfg = s.accounts[0].resolved_digest_config(s)
    assert cfg.min_imdb == 0.0          # 不被 _coalesce 当假值吞掉
    assert cfg.limit == 0


def test_per_account_independent_config(monkeypatch):
    s = _reload_settings(monkeypatch, {
        "MTEAM_USERNAME_1": "u1", "MTEAM_API_KEY_1": "k1",
        "MTEAM_DIGEST_TYPES_1": "movie",
        "MTEAM_USERNAME_2": "u2", "MTEAM_API_KEY_2": "k2",
        "MTEAM_DIGEST_TYPES_2": "tvshow",
    })
    cfg1 = s.accounts[0].resolved_digest_config(s)
    cfg2 = s.accounts[1].resolved_digest_config(s)
    assert cfg1.types == ["movie"]
    assert cfg2.types == ["tvshow"]
