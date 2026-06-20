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
