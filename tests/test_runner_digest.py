import asyncio
import contextlib
import logging
from pathlib import Path

from mteam_cli.automation.runner import _compose_body
import mteam_cli.automation.runner as runner_mod
from mteam_cli.core.config import Account, Settings
from mteam_cli.core.models import CheckinResult


def _logger():
    return logging.getLogger("test")


def _settings_stub():
    """最小 Settings（digest 全局默认走字段默认值）；不依赖 env/TOML 文件。"""
    return Settings(
        base_url="https://zp.m-team.io",
        api_base_url="https://api.m-team.cc/api",
        headless=True,
        slow_mo_ms=0,
        timeout_ms=1000,
        auth_dir=Path("/tmp/mteam-test/auth"),
        log_dir=Path("/tmp/mteam-test/logs"),
        artifact_dir=Path("/tmp/mteam-test/artifacts"),
    )


# ── _compose_body：2 参，只看 digest_text 是否非空（无二次开关）──

def test_compose_body_failure_returns_error():
    r = CheckinResult(username="u", ok=False, error="boom")
    assert _compose_body(r, "DIGEST") == "boom"


def test_compose_body_failure_default_message():
    r = CheckinResult(username="u", ok=False)
    assert _compose_body(r, "") == "登录失败"


def test_compose_body_appends_digest_when_present():
    r = CheckinResult(username="u", ok=True, profile_text="PROFILE")
    assert _compose_body(r, "DIGEST") == "PROFILE\n\nDIGEST"


def test_compose_body_omits_when_empty():
    r = CheckinResult(username="u", ok=True, profile_text="PROFILE")
    assert _compose_body(r, "") == "PROFILE"


# ── tick 级集成：每账户用自己的 cfg/api_key 拉取 ──

def _patch_login_ok(monkeypatch, profile_text="PROFILE"):
    async def fake_login(session, account, settings, logger):
        return CheckinResult(username=account.username, ok=True, profile_text=profile_text)
    monkeypatch.setattr(runner_mod, "perform_login", fake_login)

    @contextlib.asynccontextmanager
    async def fake_ctx(settings, logger):
        class _Ctx:
            session = None
        yield _Ctx()
    monkeypatch.setattr(runner_mod, "browser_session_ctx", fake_ctx)


def _capture_hub(monkeypatch):
    captured = {}

    class FakeHub:
        async def notify(self, n):
            captured["body"] = n.body
    monkeypatch.setattr(
        runner_mod, "build_notifier_hub",
        lambda account, settings, logger: FakeHub(),
    )
    return captured


def test_tick_enabled_fetches_own_digest(monkeypatch):
    """账户开了开关 + 有 api_key → tick 用本账户 cfg 拉取并拼接。"""
    acct = Account(
        username="u", api_key="k", password="p", totp_secret="t",
        digest_enabled=True,
    )
    _patch_login_ok(monkeypatch)
    captured = _capture_hub(monkeypatch)

    seen = {}

    async def fake_fetch(account, cfg, settings, logger):
        seen["api_key"] = account.api_key
        seen["types"] = cfg.types
        return "DIGEST-TEXT"
    monkeypatch.setattr(runner_mod, "_fetch_digest_for", fake_fetch)

    asyncio.run(runner_mod.run_one_account_tick(acct, _settings_stub(), _logger()))
    assert captured["body"] == "PROFILE\n\nDIGEST-TEXT"
    assert seen["api_key"] == "k"
    assert seen["types"] == ["movie", "tvshow"]  # 继承全局默认


def test_tick_disabled_does_not_fetch(monkeypatch):
    """账户没开开关 → 不拉取，通知无 digest。"""
    acct = Account(
        username="u", api_key="k", password="p", totp_secret="t",
        digest_enabled=False,
    )
    _patch_login_ok(monkeypatch)
    captured = _capture_hub(monkeypatch)

    called = {"n": 0}

    async def fake_fetch(account, cfg, settings, logger):
        called["n"] += 1
        return "SHOULD-NOT-APPEAR"
    monkeypatch.setattr(runner_mod, "_fetch_digest_for", fake_fetch)

    asyncio.run(runner_mod.run_one_account_tick(acct, _settings_stub(), _logger()))
    assert captured["body"] == "PROFILE"
    assert called["n"] == 0


def test_tick_enabled_but_no_api_key_skips(monkeypatch):
    """开了开关但无 api_key（can_query=False）→ 跳过拉取，不报错。"""
    acct = Account(
        username="u", password="p", totp_secret="t",
        digest_enabled=True,
    )  # 无 api_key
    _patch_login_ok(monkeypatch)
    captured = _capture_hub(monkeypatch)

    called = {"n": 0}

    async def fake_fetch(account, cfg, settings, logger):
        called["n"] += 1
        return "X"
    monkeypatch.setattr(runner_mod, "_fetch_digest_for", fake_fetch)

    asyncio.run(runner_mod.run_one_account_tick(acct, _settings_stub(), _logger()))
    assert captured["body"] == "PROFILE"
    assert called["n"] == 0


def test_tick_digest_failure_does_not_break_checkin(monkeypatch):
    """digest 拉取抛异常 → _fetch_digest_for 内兜底返回空串，签到通知照常发出。"""
    acct = Account(
        username="u", api_key="k", password="p", totp_secret="t",
        digest_enabled=True,
    )
    _patch_login_ok(monkeypatch)
    captured = _capture_hub(monkeypatch)

    # 真实 _fetch_digest_for 的兜底：让底层 fetch 抛异常
    async def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(runner_mod, "fetch_high_score_digest", boom)

    # 不打桩 _fetch_digest_for —— 走真实兜底路径
    asyncio.run(runner_mod.run_one_account_tick(acct, _settings_stub(), _logger()))
    assert captured["body"] == "PROFILE"  # digest 空，签到照常


def test_tick_per_account_independent_types(monkeypatch):
    """两账户不同 types → 各拉各的 cfg。"""
    a1 = Account(username="u1", api_key="k1", password="p", totp_secret="t",
                 digest_enabled=True, digest_types=["movie"])
    a2 = Account(username="u2", api_key="k2", password="p", totp_secret="t",
                 digest_enabled=True, digest_types=["tvshow"])
    _patch_login_ok(monkeypatch)
    _capture_hub(monkeypatch)

    seen = []

    async def fake_fetch(account, cfg, settings, logger):
        seen.append((account.username, cfg.types))
        return "D"
    monkeypatch.setattr(runner_mod, "_fetch_digest_for", fake_fetch)

    s = _settings_stub()
    asyncio.run(runner_mod.run_one_account_tick(a1, s, _logger()))
    asyncio.run(runner_mod.run_one_account_tick(a2, s, _logger()))
    assert seen == [("u1", ["movie"]), ("u2", ["tvshow"])]


def test_tick_login_failure_body_is_error(monkeypatch):
    """登录失败 → body 为错误信息，且不尝试拉 digest。"""
    acct = Account(
        username="u", api_key="k", password="p", totp_secret="t",
        digest_enabled=True,
    )

    async def fake_login(session, account, settings, logger):
        return CheckinResult(username=account.username, ok=False, error="登录失败了")
    monkeypatch.setattr(runner_mod, "perform_login", fake_login)

    @contextlib.asynccontextmanager
    async def fake_ctx(settings, logger):
        class _Ctx:
            session = None
        yield _Ctx()
    monkeypatch.setattr(runner_mod, "browser_session_ctx", fake_ctx)

    captured = _capture_hub(monkeypatch)
    called = {"n": 0}

    async def fake_fetch(account, cfg, settings, logger):
        called["n"] += 1
        return "X"
    monkeypatch.setattr(runner_mod, "_fetch_digest_for", fake_fetch)

    asyncio.run(runner_mod.run_one_account_tick(acct, _settings_stub(), _logger()))
    assert captured["body"] == "登录失败了"
    assert called["n"] == 0  # 失败不拉 digest


def test_tick_no_keepalive_creds_skips(monkeypatch):
    """无保活凭证 → 跳过，返回 skipped 结果。"""
    acct = Account(username="u", api_key="k", digest_enabled=True)  # 无 password/totp
    result = asyncio.run(runner_mod.run_one_account_tick(acct, _settings_stub(), _logger()))
    assert result.skipped is True
    assert result.ok is False
