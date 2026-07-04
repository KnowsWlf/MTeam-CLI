"""TOML 配置解析测试（任务 1）。用 tmp_path 写临时 TOML，断言值对象。"""

import textwrap

import pytest

import mteam_cli.core.config as config_mod
from mteam_cli.core.config import Settings

# 开发机跑测试时，真实 .env 已被 dotenv 载入 os.environ；混合式 env 覆盖会让
# 这些真实密钥盖过临时 TOML。任务 1 测的是「纯 TOML」行为，故清掉可能干扰的
# 密钥类 env（env 覆盖单独在 test_env_overrides_* 里显式设置后再测）。
_SECRET_ENV_PREFIXES = ("MTEAM_PASSWORD_", "MTEAM_TOTP_SECRET_", "MTEAM_API_KEY_")


@pytest.fixture(autouse=True)
def _clear_secret_env(monkeypatch):
    import os
    for key in list(os.environ):
        if key.startswith(_SECRET_ENV_PREFIXES) or key == "NOTIFY_SMTP_PASSWORD":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("MTEAM_CONFIG", raising=False)


def _write(tmp_path, toml_text: str):
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(toml_text), encoding="utf-8")
    return p


def test_from_toml_minimal(tmp_path):
    """只有一个 data-only 账户（username+api_key）。"""
    path = _write(tmp_path, """
        [[account]]
        username = "riddd"
        api_key = "KEY1"
    """)
    s = Settings.from_toml(path)
    assert len(s.accounts) == 1
    a = s.accounts[0]
    assert a.username == "riddd"
    assert a.api_key == "KEY1"
    assert a.can_query is True
    assert a.can_keepalive is False


def test_from_toml_full_account(tmp_path):
    """全字段账户：保活 + 查询 + notify + digest 覆盖。"""
    path = _write(tmp_path, """
        [[account]]
        username = "Bytewild"
        password = "pw"
        totp_secret = "tt"
        api_key = "KEY"
        digest_enabled = true
        [account.notify]
        telegram_token = "tg"
        telegram_chat_id = "cid"
        feishu_token = "fs"
        smtp_to = "me@foxmail.com"
        [account.digest]
        types = ["music"]
        min_seeders = 50
    """)
    s = Settings.from_toml(path)
    a = s.accounts[0]
    assert a.can_keepalive is True
    assert a.password == "pw"
    assert a.totp_secret == "tt"
    assert a.telegram_token == "tg"
    assert a.telegram_chat_id == "cid"
    assert a.feishu_token == "fs"
    assert a.smtp_to == "me@foxmail.com"
    assert a.digest_enabled is True
    assert a.digest_types == ["music"]
    assert a.digest_min_seeders == 50
    # 未覆盖的 digest 字段保持 None（继承全局）
    assert a.digest_min_imdb is None
    assert a.digest_hours is None
    assert a.digest_limit is None


def test_global_digest_defaults(tmp_path):
    """[digest] 全局值进 Settings.digest_*。"""
    path = _write(tmp_path, """
        [digest]
        min_imdb = 7.0
        min_seeders = 15
        types = ["movie", "tvshow", "music"]
        hours = 48
        limit = 5
        [[account]]
        username = "u"
        api_key = "k"
    """)
    s = Settings.from_toml(path)
    assert s.digest_min_imdb == 7.0
    assert s.digest_min_seeders == 15
    assert s.digest_types == ["movie", "tvshow", "music"]
    assert s.digest_hours == 48
    assert s.digest_limit == 5


def test_global_digest_falls_back_to_hardcoded(tmp_path):
    """无 [digest] 段 → 用硬编码默认（8.0/30/[movie,tvshow]/24/10）。"""
    path = _write(tmp_path, """
        [[account]]
        username = "u"
        api_key = "k"
    """)
    s = Settings.from_toml(path)
    assert s.digest_min_imdb == 8.0
    assert s.digest_min_seeders == 30
    assert s.digest_types == ["movie", "tvshow"]
    assert s.digest_hours == 24
    assert s.digest_limit == 10


def test_account_digest_override_partial(tmp_path):
    """[account.digest] 只写 types → 其余经 resolved_digest_config 继承全局。"""
    path = _write(tmp_path, """
        [digest]
        min_imdb = 8.0
        min_seeders = 30
        [[account]]
        username = "u"
        api_key = "k"
        [account.digest]
        types = ["adult"]
    """)
    s = Settings.from_toml(path)
    cfg = s.accounts[0].resolved_digest_config(s)
    assert cfg.types == ["adult"]       # 账户覆盖
    assert cfg.min_imdb == 8.0          # 继承全局
    assert cfg.min_seeders == 30


def test_zero_values_not_swallowed(tmp_path):
    """账户 digest 覆盖 min_imdb=0.0 / limit=0 / min_seeders=0 → 不被吞。"""
    path = _write(tmp_path, """
        [[account]]
        username = "u"
        api_key = "k"
        [account.digest]
        min_imdb = 0.0
        limit = 0
        min_seeders = 0
    """)
    s = Settings.from_toml(path)
    cfg = s.accounts[0].resolved_digest_config(s)
    assert cfg.min_imdb == 0.0
    assert cfg.limit == 0
    assert cfg.min_seeders == 0


def test_multi_account_independent(tmp_path):
    """两账户不同 digest.types → 各自独立。"""
    path = _write(tmp_path, """
        [[account]]
        username = "u1"
        api_key = "k1"
        [account.digest]
        types = ["movie"]

        [[account]]
        username = "u2"
        api_key = "k2"
        [account.digest]
        types = ["tvshow"]
    """)
    s = Settings.from_toml(path)
    assert len(s.accounts) == 2
    assert s.accounts[0].resolved_digest_config(s).types == ["movie"]
    assert s.accounts[1].resolved_digest_config(s).types == ["tvshow"]


def test_smtp_global(tmp_path):
    """[smtp] → Settings.smtp_*。"""
    path = _write(tmp_path, """
        [smtp]
        host = "smtp.qq.com"
        port = 587
        user = "me@qq.com"
        password = "authcode"
        from = "me@qq.com"
        use_tls = false
        [[account]]
        username = "u"
        api_key = "k"
    """)
    s = Settings.from_toml(path)
    assert s.smtp_host == "smtp.qq.com"
    assert s.smtp_port == 587
    assert s.smtp_user == "me@qq.com"
    assert s.smtp_password == "authcode"
    assert s.smtp_from == "me@qq.com"
    assert s.smtp_use_tls is False


def test_smtp_defaults(tmp_path):
    """无 [smtp] → 默认（host 空、port 465、use_tls True）。"""
    path = _write(tmp_path, """
        [[account]]
        username = "u"
        api_key = "k"
    """)
    s = Settings.from_toml(path)
    assert s.smtp_host == ""
    assert s.smtp_port == 465
    assert s.smtp_use_tls is True


def test_site_and_schedule(tmp_path):
    """[site] / [schedule] → 对应字段；缺省用默认。"""
    path = _write(tmp_path, """
        [site]
        base_url = "https://custom.m-team.io"
        api_base_url = "https://api.m-team.io/api"
        headless = false
        timeout_ms = 30000
        [schedule]
        window = "10:00-12:00"
        pre_delay_range = "5-100"
        heartbeat_hours = 2
        [[account]]
        username = "u"
        api_key = "k"
    """)
    s = Settings.from_toml(path)
    assert s.base_url == "https://custom.m-team.io"
    assert s.api_base_url == "https://api.m-team.io/api"
    assert s.headless is False
    assert s.timeout_ms == 30000
    assert s.schedule_window == "10:00-12:00"
    assert s.schedule_pre_delay_range == "5-100"
    assert s.schedule_heartbeat_hours == 2


def test_site_defaults(tmp_path):
    """无 [site]/[schedule] → 用硬编码默认。"""
    path = _write(tmp_path, """
        [[account]]
        username = "u"
        api_key = "k"
    """)
    s = Settings.from_toml(path)
    assert s.base_url == "https://zp.m-team.io"
    assert s.api_base_url == "https://api.m-team.cc/api"
    assert s.headless is True
    assert s.timeout_ms == 60000
    assert s.schedule_window == "09:00-11:00"


# ── 任务 2：混合式 env 密钥覆盖 ──

def test_env_overrides_api_key(tmp_path, monkeypatch):
    """TOML 有 api_key + env MTEAM_API_KEY_1 → 用 env。"""
    path = _write(tmp_path, """
        [[account]]
        username = "u"
        api_key = "FROM_TOML"
    """)
    monkeypatch.setenv("MTEAM_API_KEY_1", "FROM_ENV")
    s = Settings.from_toml(path)
    assert s.accounts[0].api_key == "FROM_ENV"


def test_env_overrides_password_and_totp(tmp_path, monkeypatch):
    path = _write(tmp_path, """
        [[account]]
        username = "u"
        password = "toml_pw"
        totp_secret = "toml_tt"
        api_key = "k"
    """)
    monkeypatch.setenv("MTEAM_PASSWORD_1", "env_pw")
    monkeypatch.setenv("MTEAM_TOTP_SECRET_1", "env_tt")
    s = Settings.from_toml(path)
    assert s.accounts[0].password == "env_pw"
    assert s.accounts[0].totp_secret == "env_tt"


def test_env_overrides_smtp_password(tmp_path, monkeypatch):
    path = _write(tmp_path, """
        [smtp]
        host = "smtp.qq.com"
        password = "toml_authcode"
        [[account]]
        username = "u"
        api_key = "k"
    """)
    monkeypatch.setenv("NOTIFY_SMTP_PASSWORD", "env_authcode")
    s = Settings.from_toml(path)
    assert s.smtp_password == "env_authcode"


def test_empty_env_does_not_override(tmp_path, monkeypatch):
    """env 设为空串 → 不覆盖，仍用 TOML 值（「空即不设」）。"""
    path = _write(tmp_path, """
        [[account]]
        username = "u"
        api_key = "FROM_TOML"
    """)
    monkeypatch.setenv("MTEAM_API_KEY_1", "   ")
    s = Settings.from_toml(path)
    assert s.accounts[0].api_key == "FROM_TOML"


def test_env_index_matches_toml_order(tmp_path, monkeypatch):
    """账户 2 的密钥用 _2 后缀，按数组 1-based 序号。"""
    path = _write(tmp_path, """
        [[account]]
        username = "u1"
        api_key = "toml1"

        [[account]]
        username = "u2"
        api_key = "toml2"
    """)
    monkeypatch.setenv("MTEAM_API_KEY_2", "env2")
    s = Settings.from_toml(path)
    assert s.accounts[0].api_key == "toml1"   # _1 未设 → 用 TOML
    assert s.accounts[1].api_key == "env2"    # _2 覆盖


# ── 任务 3：--config 全局参数 + 三级发现 ──

from pathlib import Path

from mteam_cli.core.config import _resolve_config_path


def test_resolve_config_path_explicit(monkeypatch):
    """显式 path 优先，即使 MTEAM_CONFIG 也存在。"""
    monkeypatch.setenv("MTEAM_CONFIG", "/from/env.toml")
    assert _resolve_config_path(Path("/explicit.toml")) == Path("/explicit.toml")


def test_resolve_config_path_env(monkeypatch):
    monkeypatch.setenv("MTEAM_CONFIG", "/from/env.toml")
    assert _resolve_config_path(None) == Path("/from/env.toml")


def test_resolve_config_path_default(monkeypatch):
    monkeypatch.delenv("MTEAM_CONFIG", raising=False)
    got = _resolve_config_path(None)
    assert got.name == "config.toml"
    assert got == config_mod.ROOT_DIR / "config.toml"


def test_missing_file_errors(tmp_path):
    """路径不存在 → SystemExit，提示指向 template。"""
    missing = tmp_path / "nope.toml"
    with pytest.raises(SystemExit) as ei:
        Settings.from_toml(missing)
    assert "config.toml.template" in str(ei.value)
