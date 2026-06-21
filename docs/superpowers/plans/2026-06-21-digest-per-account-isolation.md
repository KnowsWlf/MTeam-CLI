# Digest 每账户隔离重构（0.4.0）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 把 digest 从「全站共用一次拉取」改为「每账户用自己的 api_key + 自己的配置独立拉取」，并支持每账户可选覆盖全局默认。

**架构：** 新增 `DigestConfig` 值对象 + `Account.resolved_digest_config(settings)` 方法承载「账户覆盖 then 继承全局」的合并规则（单一来源）；`runner.py` 删掉共享文本逻辑改为每账户自包含拉取；`digest` 命令与 runner 统一消费 `resolved_digest_config`。

**技术栈：** Python 3.11+、dataclass（frozen/slots）、pytest（monkeypatch + `importlib.reload` 重载 config 模块读 env）、urllib（既有 API 层不动）。

**设计文档：** `docs/superpowers/specs/2026-06-21-digest-per-account-isolation-design.md`

**起点注意：** 工作区 `automation/runner.py` 有一处未提交的临时调试日志（上次排查 bug 加的）。任务 4 会整体重写 runner 的 digest 部分，届时这段调试日志被正式日志取代。**任务 4 开始前先 `git checkout src/mteam_cli/automation/runner.py` 丢弃这段临时改动**，从干净的 0.3.2 版本开始改。

---

## 文件结构

| 文件 | 职责 | 本计划改动 |
|---|---|---|
| `core/config.py` | Settings + Account + env 解析 | +`DigestConfig`、+`_coalesce`、+`_suffixed_int/_suffixed_float`、`Account` +4 覆盖字段 +`resolved_digest_config`、`_parse_accounts` 读新 env |
| `automation/runner.py` | 保活 tick 编排 | 删 `_maybe_fetch_digest`、改 `run_one_account_tick`/`run_all_accounts`/`_compose_body`、+`_fetch_digest_for` |
| `cli/commands/digest.py` | digest 预览命令 | 改用 `resolved_digest_config`，三级优先级 |
| `tests/test_config_digest.py` | config digest 测试 | +`resolved_digest_config`/`_coalesce`/`_suffixed_*` 用例 |
| `tests/test_runner_digest.py` | runner digest 测试 | 删旧共享用例、+每账户隔离用例 |
| `.env.template` | 配置示例 | +每账户 `MTEAM_DIGEST_*_i` 示例 |
| `CLAUDE.md` | 项目说明 | digest 段更新为「每账户隔离」 |
| `pyproject.toml` / `src/mteam_cli/__init__.py` | 版本 | 0.3.2 → 0.4.0 |

---

## 任务 1：`DigestConfig` 值对象 + `_coalesce` 辅助

**文件：**
- 修改：`src/mteam_cli/core/config.py`（在 `_suffixed` 之后、`Account` 之前插入）
- 测试：`tests/test_config_digest.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_config_digest.py` 末尾追加：

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_config_digest.py -k "coalesce or digest_config" -v`
预期：FAIL，`ImportError: cannot import name 'DigestConfig'`

- [ ] **步骤 3：编写最少实现代码**

在 `src/mteam_cli/core/config.py` 的 `_suffixed` 函数之后插入：

```python
def _coalesce(value, default):
    """返回 value，除非它是 None（此时返回 default）。

    不能用 ``value or default``：``0.0`` / ``0`` 是合法配置值，
    ``or`` 会把它们当假值吞掉。
    """
    return value if value is not None else default


@dataclass(slots=True, frozen=True)
class DigestConfig:
    """一个账户解析后的最终 digest 参数（全局默认 + 账户覆盖合并后）。"""

    types: list[str]
    min_imdb: float
    hours: int
    limit: int
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_config_digest.py -k "coalesce or digest_config" -v`
预期：PASS（3 个）

- [ ] **步骤 5：Commit**

```bash
git add src/mteam_cli/core/config.py tests/test_config_digest.py
git commit -m "feat(config): DigestConfig 值对象 + _coalesce 辅助"
```

---

## 任务 2：可空 env 解析辅助 `_suffixed_int` / `_suffixed_float`

**文件：**
- 修改：`src/mteam_cli/core/config.py`（在 `_suffixed` 之后）
- 测试：`tests/test_config_digest.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_config_digest.py` 末尾追加：

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_config_digest.py -k "suffixed_int or suffixed_float" -v`
预期：FAIL，`ImportError: cannot import name '_suffixed_int'`

- [ ] **步骤 3：编写最少实现代码**

在 `src/mteam_cli/core/config.py` 的 `_suffixed` 函数之后（`_coalesce` 之前或之后均可）插入：

```python
def _suffixed_int(name: str, i: int) -> int | None:
    raw = os.getenv(f"{name}_{i}")
    if raw is None or not raw.strip():
        return None
    return int(raw.strip())


def _suffixed_float(name: str, i: int) -> float | None:
    raw = os.getenv(f"{name}_{i}")
    if raw is None or not raw.strip():
        return None
    return float(raw.strip())
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_config_digest.py -k "suffixed_int or suffixed_float" -v`
预期：PASS（4 个）

- [ ] **步骤 5：Commit**

```bash
git add src/mteam_cli/core/config.py tests/test_config_digest.py
git commit -m "feat(config): 可空 env 解析辅助 _suffixed_int/_suffixed_float"
```

---

## 任务 3：`Account` 覆盖字段 + `resolved_digest_config` + env 解析

**文件：**
- 修改：`src/mteam_cli/core/config.py`（`Account` 类定义 + `_parse_accounts`）
- 测试：`tests/test_config_digest.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_config_digest.py` 末尾追加：

```python
def test_resolved_config_all_inherited(monkeypatch):
    # 账户无任何覆盖 → 完全继承全局
    s = _reload_settings(monkeypatch, {
        "MTEAM_USERNAME_1": "u1", "MTEAM_API_KEY_1": "k1",
    })
    cfg = s.accounts[0].resolved_digest_config(s)
    assert cfg.types == ["movie", "tvshow"]
    assert cfg.min_imdb == 8.0
    assert cfg.hours == 24
    assert cfg.limit == 10


def test_resolved_config_partial_override(monkeypatch):
    # 只覆盖 types，其余继承全局
    s = _reload_settings(monkeypatch, {
        "MTEAM_USERNAME_1": "u1", "MTEAM_API_KEY_1": "k1",
        "MTEAM_DIGEST_TYPES_1": "movie",
    })
    cfg = s.accounts[0].resolved_digest_config(s)
    assert cfg.types == ["movie"]      # 账户值
    assert cfg.min_imdb == 8.0          # 继承
    assert cfg.hours == 24              # 继承
    assert cfg.limit == 10              # 继承


def test_resolved_config_full_override(monkeypatch):
    s = _reload_settings(monkeypatch, {
        "MTEAM_USERNAME_1": "u1", "MTEAM_API_KEY_1": "k1",
        "MTEAM_DIGEST_TYPES_1": "tvshow,music",
        "MTEAM_DIGEST_MIN_IMDB_1": "7.0",
        "MTEAM_DIGEST_HOURS_1": "48",
        "MTEAM_DIGEST_LIMIT_1": "3",
    })
    cfg = s.accounts[0].resolved_digest_config(s)
    assert cfg.types == ["tvshow", "music"]
    assert cfg.min_imdb == 7.0
    assert cfg.hours == 48
    assert cfg.limit == 3


def test_resolved_config_zero_imdb_not_swallowed(monkeypatch):
    # min_imdb=0 覆盖必须保留（回归保护：_coalesce 而非 or）
    s = _reload_settings(monkeypatch, {
        "MTEAM_USERNAME_1": "u1", "MTEAM_API_KEY_1": "k1",
        "MTEAM_DIGEST_MIN_IMDB_1": "0",
    })
    cfg = s.accounts[0].resolved_digest_config(s)
    assert cfg.min_imdb == 0.0


def test_per_account_independent_config(monkeypatch):
    # 两账户不同覆盖，互不影响
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_config_digest.py -k "resolved_config or per_account_independent" -v`
预期：FAIL，`TypeError: __init__() got an unexpected keyword argument 'digest_types'`（或 `AttributeError: resolved_digest_config`）

- [ ] **步骤 3a：给 `Account` 加覆盖字段**

在 `src/mteam_cli/core/config.py` 的 `Account` 类中，把现有的 `digest_enabled: bool = False` 行替换为下面整块（紧随其后加 4 个可空字段）：

```python
    digest_enabled: bool = False
    # ── per-account digest overrides（None = 继承 Settings 全局默认）──
    digest_types: list[str] | None = None
    digest_min_imdb: float | None = None
    digest_hours: int | None = None
    digest_limit: int | None = None
```

- [ ] **步骤 3b：给 `Account` 加 `resolved_digest_config` 方法**

在 `Account` 类内、`has_smtp` 方法之后插入（注意 `DigestConfig` 已在任务 1 定义于 `Account` 之前，可直接引用）：

```python
    def resolved_digest_config(self, settings: "Settings") -> "DigestConfig":
        """合并账户覆盖与全局默认，返回该账户最终的 digest 配置。

        合并规则唯一来源：账户字段非 None 则用账户值，否则继承全局。
        """
        return DigestConfig(
            types=self.digest_types or settings.digest_types,
            min_imdb=_coalesce(self.digest_min_imdb, settings.digest_min_imdb),
            hours=_coalesce(self.digest_hours, settings.digest_hours),
            limit=_coalesce(self.digest_limit, settings.digest_limit),
        )
```

- [ ] **步骤 3c：`_parse_accounts` 读取每账户覆盖 env**

在 `src/mteam_cli/core/config.py` 的 `_parse_accounts` 中，找到构造 `Account(...)` 的 `digest_enabled=_env_bool(f"MTEAM_DIGEST_ENABLED_{i}", False),` 这一行，在其后补充 4 行：

```python
                    digest_enabled=_env_bool(f"MTEAM_DIGEST_ENABLED_{i}", False),
                    digest_types=(
                        [t.strip() for t in raw.split(",") if t.strip()]
                        if (raw := _suffixed("MTEAM_DIGEST_TYPES", i))
                        else None
                    ),
                    digest_min_imdb=_suffixed_float("MTEAM_DIGEST_MIN_IMDB", i),
                    digest_hours=_suffixed_int("MTEAM_DIGEST_HOURS", i),
                    digest_limit=_suffixed_int("MTEAM_DIGEST_LIMIT", i),
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_config_digest.py -v`
预期：PASS（含原有用例 + 新增 5 个 resolved_config 用例）

- [ ] **步骤 5：Commit**

```bash
git add src/mteam_cli/core/config.py tests/test_config_digest.py
git commit -m "feat(config): Account digest 覆盖字段 + resolved_digest_config 合并规则"
```

---

## 任务 4：重写 `runner.py` digest 路径为每账户隔离

**文件：**
- 修改：`src/mteam_cli/automation/runner.py`
- 测试：`tests/test_runner_digest.py`

**前置：丢弃临时调试日志，从干净 0.3.2 起步：**

```bash
git checkout src/mteam_cli/automation/runner.py
```

- [ ] **步骤 1：重写测试文件**

整体替换 `tests/test_runner_digest.py` 为：

```python
import asyncio
import contextlib
import logging

from mteam_cli.automation import runner as runner_mod
from mteam_cli.automation.runner import _compose_body, _fetch_digest_for
from mteam_cli.core.config import Account, DigestConfig, Settings
from mteam_cli.core.models import CheckinResult


def _logger():
    return logging.getLogger("test")


# ── _compose_body：只看 digest_text 是否非空（不再二次判断开关）──


def test_compose_body_failure_returns_error():
    r = CheckinResult(username="u", ok=False, error="boom")
    assert _compose_body(r, "DIGEST") == "boom"


def test_compose_body_appends_digest_when_present():
    r = CheckinResult(username="u", ok=True, profile_text="PROFILE")
    assert _compose_body(r, "DIGEST") == "PROFILE\n\nDIGEST"


def test_compose_body_empty_digest_omitted():
    r = CheckinResult(username="u", ok=True, profile_text="PROFILE")
    assert _compose_body(r, "") == "PROFILE"


# ── _fetch_digest_for：用账户自己的 cfg 拉取 ──


def test_fetch_digest_for_uses_account_config(monkeypatch):
    captured = {}

    async def fake_fetch(api_key, *, base_url, min_imdb, types, hours, limit):
        captured.update(api_key=api_key, types=types, min_imdb=min_imdb,
                        hours=hours, limit=limit)
        return [{"imdb": 9.0, "title": "片", "type": "电影"}]

    monkeypatch.setattr(runner_mod, "fetch_high_score_digest", fake_fetch)
    monkeypatch.setattr(runner_mod, "format_digest", lambda rows, *, min_imdb: "DIGEST-OUT")

    acct = Account(username="u", api_key="KEY")
    cfg = DigestConfig(types=["movie"], min_imdb=7.0, hours=48, limit=3)
    out = asyncio.run(_fetch_digest_for(acct, cfg, Settings.from_env(), _logger()))

    assert out == "DIGEST-OUT"
    assert captured["api_key"] == "KEY"      # 用账户自己的 key
    assert captured["types"] == ["movie"]
    assert captured["min_imdb"] == 7.0
    assert captured["hours"] == 48
    assert captured["limit"] == 3


def test_fetch_digest_for_failure_returns_blank(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(runner_mod, "fetch_high_score_digest", boom)

    acct = Account(username="u", api_key="KEY")
    cfg = DigestConfig(types=["movie"], min_imdb=8.0, hours=24, limit=10)
    out = asyncio.run(_fetch_digest_for(acct, cfg, Settings.from_env(), _logger()))
    assert out == ""   # 失败返回空串，不抛


# ── run_one_account_tick：每账户自包含 ──


def _patch_login_ok(monkeypatch):
    async def fake_login(session, account, settings, logger):
        return CheckinResult(username=account.username, ok=True, profile_text="PROFILE")
    monkeypatch.setattr(runner_mod, "perform_login", fake_login)

    @contextlib.asynccontextmanager
    async def fake_ctx(settings, logger):
        class _Ctx:
            session = None
        yield _Ctx()
    monkeypatch.setattr(runner_mod, "browser_session_ctx", fake_ctx)


def test_tick_enabled_account_appends_own_digest(monkeypatch):
    _patch_login_ok(monkeypatch)

    async def fake_fetch_digest_for(account, cfg, settings, logger):
        return f"DIGEST[{account.username}]"
    monkeypatch.setattr(runner_mod, "_fetch_digest_for", fake_fetch_digest_for)

    captured = {}

    class FakeHub:
        async def notify(self, n):
            captured["body"] = n.body
    monkeypatch.setattr(runner_mod, "build_notifier_hub",
                        lambda account, settings, logger: FakeHub())

    acct = Account(username="u", api_key="k", password="p", totp_secret="t",
                   digest_enabled=True)
    asyncio.run(runner_mod.run_one_account_tick(acct, Settings.from_env(), _logger()))
    assert captured["body"] == "PROFILE\n\nDIGEST[u]"


def test_tick_disabled_account_no_digest(monkeypatch):
    _patch_login_ok(monkeypatch)

    called = {"n": 0}

    async def fake_fetch_digest_for(account, cfg, settings, logger):
        called["n"] += 1
        return "SHOULD-NOT-APPEAR"
    monkeypatch.setattr(runner_mod, "_fetch_digest_for", fake_fetch_digest_for)

    captured = {}

    class FakeHub:
        async def notify(self, n):
            captured["body"] = n.body
    monkeypatch.setattr(runner_mod, "build_notifier_hub",
                        lambda account, settings, logger: FakeHub())

    acct = Account(username="u", api_key="k", password="p", totp_secret="t",
                   digest_enabled=False)
    asyncio.run(runner_mod.run_one_account_tick(acct, Settings.from_env(), _logger()))
    assert captured["body"] == "PROFILE"
    assert called["n"] == 0   # 未开启 → 根本不拉


def test_tick_enabled_but_no_api_key_skips(monkeypatch):
    _patch_login_ok(monkeypatch)

    called = {"n": 0}

    async def fake_fetch_digest_for(account, cfg, settings, logger):
        called["n"] += 1
        return "X"
    monkeypatch.setattr(runner_mod, "_fetch_digest_for", fake_fetch_digest_for)

    class FakeHub:
        async def notify(self, n):
            pass
    monkeypatch.setattr(runner_mod, "build_notifier_hub",
                        lambda account, settings, logger: FakeHub())

    # digest_enabled 但无 api_key（can_query=False）→ 不拉
    acct = Account(username="u", password="p", totp_secret="t", digest_enabled=True)
    asyncio.run(runner_mod.run_one_account_tick(acct, Settings.from_env(), _logger()))
    assert called["n"] == 0
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_runner_digest.py -v`
预期：FAIL，`ImportError: cannot import name '_fetch_digest_for'`（以及 `_compose_body` 签名不符）

- [ ] **步骤 3：重写 runner.py 的 digest 部分**

在 `src/mteam_cli/automation/runner.py` 中执行以下三处改动。

**3a. 顶部 import**：把模块顶部对 digest 的延迟 import 改为静态 import（方便测试 monkeypatch）。在文件顶部 import 区加：

```python
from mteam_cli.api import fetch_high_score_digest, format_digest
```

**3b. `run_one_account_tick`**：整体替换为（去掉 `digest_text` 参数，改为内部用账户自己的 cfg 拉取）：

```python
async def run_one_account_tick(
    account: Account,
    settings: Settings,
    logger: logging.Logger,
) -> CheckinResult:
    """Run one account's keep-alive login end-to-end and notify the outcome.

    Digest is fetched per-account with that account's own api_key + resolved
    config — fully isolated, no shared text across accounts.
    """
    if not account.can_keepalive:
        logger.warning("[%s] 缺少保活凭证，跳过", account.username)
        return CheckinResult(username=account.username, ok=False, skipped=True)

    hub = build_notifier_hub(account, settings, logger)
    try:
        async with browser_session_ctx(settings, logger) as ctx:
            result = await perform_login(ctx.session, account, settings, logger)
    except Exception as exc:  # noqa: BLE001 — isolate per account
        logger.exception("[%s] 保活过程崩溃", account.username)
        result = CheckinResult(username=account.username, ok=False, error=str(exc))

    digest_text = ""
    if result.ok and account.digest_enabled:
        if account.can_query:
            cfg = account.resolved_digest_config(settings)
            digest_text = await _fetch_digest_for(account, cfg, settings, logger)
        else:
            logger.info("[%s] digest 已开启但该账户无 api_key，跳过", account.username)

    event = NotificationEvent.CHECKIN_DONE if result.ok else NotificationEvent.CHECKIN_FAILED
    title = f"[{account.username}] 签到{'成功' if result.ok else '失败'}"
    await hub.notify(
        Notification(
            event=event,
            title=title,
            body=_compose_body(result, digest_text),
        )
    )
    return result
```

**3c. `run_all_accounts`**：删掉预拉取，循环里不再传 `digest_text`。把现有 `run_all_accounts` 中这段：

```python
    digest_text = await _maybe_fetch_digest(keepalive_targets, settings, logger)

    worst = 0
    for acct in keepalive_targets:
        try:
            result = await run_one_account_tick(acct, settings, logger, digest_text)
```

替换为：

```python
    worst = 0
    for acct in keepalive_targets:
        try:
            result = await run_one_account_tick(acct, settings, logger)
```

**3d. 替换 `_compose_body` 与 `_maybe_fetch_digest`**：删除现有的 `_compose_body` 和整个 `_maybe_fetch_digest` 函数，替换为新的 `_compose_body`（两参数）+ `_fetch_digest_for`：

```python
def _compose_body(result: CheckinResult, digest_text: str) -> str:
    """签到通知正文：失败为错误；成功为 profile，有 digest 文本则拼接。"""
    if not result.ok:
        return result.error or "登录失败"
    if digest_text:
        return f"{result.profile_text}\n\n{digest_text}"
    return result.profile_text


async def _fetch_digest_for(
    account: Account,
    cfg: "DigestConfig",
    settings: Settings,
    logger: logging.Logger,
) -> str:
    """用 ``account`` 自己的 api_key + ``cfg`` 拉取并格式化 digest。

    任何失败只记日志、返回空串——digest 绝不影响签到。
    """
    try:
        rows = await fetch_high_score_digest(
            account.api_key,
            base_url=settings.api_base_url,
            min_imdb=cfg.min_imdb,
            types=cfg.types,
            hours=cfg.hours,
            limit=cfg.limit,
        )
        logger.info(
            "[%s] digest: 命中 %d 条（min_imdb=%s hours=%s types=%s）",
            account.username, len(rows), cfg.min_imdb, cfg.hours, cfg.types,
        )
        return format_digest(rows, min_imdb=cfg.min_imdb)
    except Exception:  # noqa: BLE001 — digest 失败绝不影响签到
        logger.exception("[%s] digest 拉取失败，本轮通知不含高分新片", account.username)
        return ""
```

**3e. 补 `DigestConfig` 的 import**：在 runner.py 顶部 import 区，把现有的

```python
from mteam_cli.core.config import Account, Settings
```

改为：

```python
from mteam_cli.core.config import Account, DigestConfig, Settings
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_runner_digest.py -v`
预期：PASS（9 个）

- [ ] **步骤 5：Commit**

```bash
git add src/mteam_cli/automation/runner.py tests/test_runner_digest.py
git commit -m "refactor(runner): digest 改为每账户隔离拉取，删除共享文本逻辑"
```

---

## 任务 5：`digest` 命令统一消费 `resolved_digest_config`

**文件：**
- 修改：`src/mteam_cli/cli/commands/digest.py:44-66`（`_run` 函数）

- [ ] **步骤 1：改 `_run` 用 resolved_digest_config**

把 `src/mteam_cli/cli/commands/digest.py` 的 `_run` 函数中这段：

```python
    min_imdb = args.min_imdb if args.min_imdb is not None else settings.digest_min_imdb
    types = (
        [t.strip() for t in args.types.split(",") if t.strip()]
        if args.types
        else settings.digest_types
    )
    hours = args.hours if args.hours is not None else settings.digest_hours
    limit = args.limit if args.limit is not None else settings.digest_limit
```

替换为（三级优先级：命令行 > 账户 > 全局，账户层由 `resolved_digest_config` 提供）：

```python
    cfg = account.resolved_digest_config(settings)
    min_imdb = args.min_imdb if args.min_imdb is not None else cfg.min_imdb
    types = (
        [t.strip() for t in args.types.split(",") if t.strip()]
        if args.types
        else cfg.types
    )
    hours = args.hours if args.hours is not None else cfg.hours
    limit = args.limit if args.limit is not None else cfg.limit
```

- [ ] **步骤 2：编译 + 冒烟验证**

运行：`python -c "import mteam_cli.cli.commands.digest; print('import OK')"`
预期：`import OK`

运行：`python -m mteam_cli digest --help`
预期：正常打印 digest 命令帮助（无异常）

- [ ] **步骤 3：Commit**

```bash
git add src/mteam_cli/cli/commands/digest.py
git commit -m "refactor(digest-cmd): 统一消费 resolved_digest_config（命令行>账户>全局）"
```

---

## 任务 6：全量测试 + `.env.template` + CLAUDE.md + 版本

**文件：**
- 修改：`.env.template`、`CLAUDE.md`、`pyproject.toml:7`、`src/mteam_cli/__init__.py:3`

- [ ] **步骤 1：全量测试**

运行：`python -m pytest tests/ -v`
预期：全部 PASS（任务 1-4 新增用例 + 既有 `test_digest.py` 17 例 + `test_api_internal.py` 17 例不受影响）

运行：`python -m compileall -q src/mteam_cli && echo "compile OK"`
预期：`compile OK`

- [ ] **步骤 2：更新 `.env.template`**

在 `.env.template` 的 digest 相关段落（全局 `MTEAM_DIGEST_*`）之后，追加每账户覆盖示例：

```bash
# ── 高分新片摘要（digest）──
# 全局默认值（所有开启 digest 的账户继承，除非账户级覆盖）：
MTEAM_DIGEST_MIN_IMDB=8.0
MTEAM_DIGEST_TYPES=movie,tvshow
MTEAM_DIGEST_HOURS=24
MTEAM_DIGEST_LIMIT=10
#
# 每账户开关（默认关闭）：
MTEAM_DIGEST_ENABLED_1=true
#
# 每账户可选覆盖（不配则继承上面的全局默认）。例：账户 1 只要电影、
# 放宽到 7 分、看最近 48 小时：
# MTEAM_DIGEST_TYPES_1=movie
# MTEAM_DIGEST_MIN_IMDB_1=7.0
# MTEAM_DIGEST_HOURS_1=48
# MTEAM_DIGEST_LIMIT_1=5
#
# 可选 types（search mode）：movie 电影 / tvshow 电视剧 / music 音乐 /
#   adult 成人 / normal 综合 / waterfall 瀑布流 / rss / rankings 排行 / all 全部
#   注意：music/adult 不带 IMDB 评分，当前 digest 对其无效（见未来方向）。
```

> 若 `.env.template` 中已有全局 `MTEAM_DIGEST_*` 行，避免重复——只追加「每账户可选覆盖」注释块和 `_1` 示例。先 `grep -n DIGEST .env.template` 确认现状再编辑。

- [ ] **步骤 3：更新 CLAUDE.md digest 段**

在 `CLAUDE.md` 中找到 `api/` 小节里描述 `digest.py` 的那句（当前：「高分新片摘要：复用 `search` 拉 movie/tvshow…供 `digest` 命令与签到 runner（fetch-once）共用」），替换为：

```
- `digest.py` — 高分新片摘要：复用 `search_torrents` 拉 movie/tvshow，本地按 IMDB 阈值 + 发布时间窗过滤排序。`fetch_high_score_digest` + `format_digest`。**每账户隔离**：runner 用各账户自己的 api_key + `Account.resolved_digest_config(settings)`（全局默认 + 账户 `MTEAM_DIGEST_*_i` 可选覆盖）独立拉取，`digest` 命令同样消费 `resolved_digest_config`。
```

并在配置说明段（`MTEAM_DIGEST_*` 附近）补一句：

```
> Digest 配置为三级：全局 `MTEAM_DIGEST_*`（默认）← 账户 `MTEAM_DIGEST_*_i`（覆盖）← `digest` 命令行参数（临时覆盖）。合并规则集中在 `Account.resolved_digest_config`。
```

- [ ] **步骤 4：bump 版本到 0.4.0**

`pyproject.toml` 第 7 行：`version = "0.3.2"` → `version = "0.4.0"`
`src/mteam_cli/__init__.py` 第 3 行：`__version__ = "0.3.2"` → `__version__ = "0.4.0"`

- [ ] **步骤 5：最终验证 + Commit**

运行：`python -m pytest tests/ -q && python -m compileall -q src/mteam_cli && echo ALL-OK`
预期：全过 + `ALL-OK`

运行版本一致性核对：`grep -m1 '^version' pyproject.toml && grep __version__ src/mteam_cli/__init__.py`
预期：两处都是 `0.4.0`

```bash
git add .env.template CLAUDE.md pyproject.toml src/mteam_cli/__init__.py
git commit -m "docs+chore: digest 每账户隔离文档 + 版本 0.4.0"
```

---

## 自检结果

**1. 规格覆盖度：**
- `DigestConfig` 值对象 → 任务 1 ✓
- `_coalesce`（防 0.0 被吞）→ 任务 1 ✓
- `_suffixed_int/_suffixed_float` → 任务 2 ✓
- `Account` 4 覆盖字段 + `resolved_digest_config` → 任务 3 ✓
- `_parse_accounts` 读新 env → 任务 3 步骤 3c ✓
- 向后兼容（全局值降级为默认）→ 任务 3 `test_resolved_config_all_inherited` 验证 ✓
- runner 删 `_maybe_fetch_digest`、改三函数、+`_fetch_digest_for` → 任务 4 ✓
- 每账户用自己 api_key → 任务 4 `test_fetch_digest_for_uses_account_config` ✓
- digest 失败不影响签到 → 任务 4 `test_fetch_digest_for_failure_returns_blank` ✓
- 开关 enabled 但无 api_key → 任务 4 `test_tick_enabled_but_no_api_key_skips` ✓
- `digest` 命令统一消费 → 任务 5 ✓
- 命令行 > 账户 > 全局三级优先级 → 任务 5 ✓
- `.env.template` / CLAUDE.md / 版本 → 任务 6 ✓
- 方案 B（非 imdb）→ 设计文档已记为未来方向，本计划不实现 ✓（有意排除）

**2. 占位符扫描：** 无 TODO/待定；所有代码步骤含完整代码块；命令含预期输出。✓

**3. 类型一致性：**
- `DigestConfig(types, min_imdb, hours, limit)` 字段名在任务 1 定义，任务 3/4/5 引用一致 ✓
- `_compose_body` 全程两参数 `(result, digest_text)`（任务 4 重写后），测试与实现一致 ✓
- `_fetch_digest_for(account, cfg, settings, logger)` 签名在任务 4 测试与实现一致 ✓
- `resolved_digest_config(settings)` 在任务 3 定义，任务 4/5 调用一致 ✓
- `fetch_high_score_digest` 散参数签名与现有 `api/digest.py` 一致（不改）✓

无遗漏，无占位符，类型一致。
