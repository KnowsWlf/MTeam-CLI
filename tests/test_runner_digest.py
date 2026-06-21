import asyncio
import contextlib
import logging

from mteam_cli.automation.runner import _compose_body
import mteam_cli.automation.runner as runner_mod
from mteam_cli.core.config import Account, Settings
from mteam_cli.core.models import CheckinResult


def _acct(digest_enabled):
    return Account(username="u", api_key="k", digest_enabled=digest_enabled)


def _logger():
    return logging.getLogger("test")


def _settings_stub():
    return Settings.from_env()


def test_compose_body_failure_returns_error():
    r = CheckinResult(username="u", ok=False, error="boom")
    assert _compose_body(r, _acct(True), "DIGEST") == "boom"


def test_compose_body_enabled_appends_digest():
    r = CheckinResult(username="u", ok=True, profile_text="PROFILE")
    out = _compose_body(r, _acct(True), "DIGEST")
    assert out == "PROFILE\n\nDIGEST"


def test_compose_body_disabled_omits_digest():
    r = CheckinResult(username="u", ok=True, profile_text="PROFILE")
    assert _compose_body(r, _acct(False), "DIGEST") == "PROFILE"


def test_compose_body_enabled_but_empty_digest():
    r = CheckinResult(username="u", ok=True, profile_text="PROFILE")
    assert _compose_body(r, _acct(True), "") == "PROFILE"


def test_tick_self_fetches_digest_when_empty(monkeypatch):
    """schedule 路径：digest_text 未传、账户开了开关 → tick 自行拉取并拼接。"""
    acct = Account(
        username="u", api_key="k", password="p", totp_secret="t",
        digest_enabled=True,
    )

    async def fake_login(session, account, settings, logger):
        return CheckinResult(username=account.username, ok=True, profile_text="PROFILE")
    monkeypatch.setattr(runner_mod, "perform_login", fake_login)

    @contextlib.asynccontextmanager
    async def fake_ctx(settings, logger):
        class _Ctx:
            session = None
        yield _Ctx()
    monkeypatch.setattr(runner_mod, "browser_session_ctx", fake_ctx)

    async def fake_fetch(targets, settings, logger):
        return "DIGEST-TEXT"
    monkeypatch.setattr(runner_mod, "_maybe_fetch_digest", fake_fetch)

    captured = {}

    class FakeHub:
        async def notify(self, n):
            captured["body"] = n.body

    monkeypatch.setattr(runner_mod, "build_notifier_hub", lambda account, settings, logger: FakeHub())

    settings = _settings_stub()
    asyncio.run(runner_mod.run_one_account_tick(acct, settings, _logger()))
    assert captured["body"] == "PROFILE\n\nDIGEST-TEXT"


def test_tick_does_not_refetch_when_digest_passed(monkeypatch):
    """run 路径：digest_text 已传 → tick 不再自拉（避免重复请求）。"""
    acct = Account(
        username="u", api_key="k", password="p", totp_secret="t",
        digest_enabled=True,
    )

    async def fake_login(session, account, settings, logger):
        return CheckinResult(username=account.username, ok=True, profile_text="PROFILE")
    monkeypatch.setattr(runner_mod, "perform_login", fake_login)

    @contextlib.asynccontextmanager
    async def fake_ctx(settings, logger):
        class _Ctx:
            session = None
        yield _Ctx()
    monkeypatch.setattr(runner_mod, "browser_session_ctx", fake_ctx)

    called = {"n": 0}

    async def fake_fetch(targets, settings, logger):
        called["n"] += 1
        return "SHOULD-NOT-BE-USED"
    monkeypatch.setattr(runner_mod, "_maybe_fetch_digest", fake_fetch)

    captured = {}

    class FakeHub:
        async def notify(self, n):
            captured["body"] = n.body
    monkeypatch.setattr(runner_mod, "build_notifier_hub", lambda account, settings, logger: FakeHub())

    settings = _settings_stub()
    asyncio.run(runner_mod.run_one_account_tick(acct, settings, _logger(), "PRE-FETCHED"))
    assert captured["body"] == "PROFILE\n\nPRE-FETCHED"
    assert called["n"] == 0  # 已传 digest_text，不应再拉
