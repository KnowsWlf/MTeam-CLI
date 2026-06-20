# 高分新片摘要（High-Score Digest）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在每日签到通知尾部附上当天发布的高分影视摘要（默认 IMDB≥8.0、过去 24h 的电影/电视剧），并提供 `mteam-cli digest` 独立预览命令。

**架构：** 复用现有 `search_torrents()` 拉 movie/tvshow 最新结果 → 本地按 IMDB 阈值 + 发布时间窗过滤排序（新模块 `api/digest.py`）。一轮调度只用第一个有 api_key 的账户拉一次，拼进**开启了开关**的账户签到通知。账户级开关 `MTEAM_DIGEST_ENABLED_<n>`（默认 false）+ 全局参数。保活核心 `automation/login.py` 不动；digest 拉取失败只记日志、签到照常。

**技术栈：** Python 3.11+，stdlib（`datetime`/`urllib` 经由现有 `api_post`），pytest（本计划首次引入测试套件），现有 `cli/_query.py` 脚手架。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `pyproject.toml` | 修改：新增 `[project.optional-dependencies] dev = ["pytest"]` |
| `src/mteam_cli/api/digest.py` | **新增**：`fetch_high_score_digest` + `format_digest` + 解析辅助 `_parse_float`/`_age_hours`/`_shape`/`TYPE_LABELS` |
| `src/mteam_cli/api/__init__.py` | 修改：导出 digest 函数 |
| `src/mteam_cli/core/config.py` | 修改：`Account.digest_enabled` + `Settings.digest_*` 四个字段 + 解析 |
| `src/mteam_cli/automation/runner.py` | 修改：`run_all_accounts` fetch-once + `run_one_account_tick` 拼接 digest |
| `src/mteam_cli/cli/commands/digest.py` | **新增**：`digest` 命令（复用 `_query` 脚手架） |
| `src/mteam_cli/cli/main.py` | 修改：注册 `digest` 命令 |
| `.env.template` | 修改：新增 digest 配置段（含类型备注） |
| `docker-compose.yaml` / `kubernetes-manifests/statefulset.yaml` | 修改：env 示例 |
| `CLAUDE.md` / `README.md` | 修改：文档 |
| `tests/conftest.py` | **新增**：pytest 路径配置 |
| `tests/test_digest.py` | **新增**：digest 过滤/格式化单测 |
| `tests/test_config_digest.py` | **新增**：digest 配置解析单测 |

---

## 任务 1：引入 pytest 测试基础设施

项目此前无测试套件（CLAUDE.md 明确"no test suite"）。本功能用 TDD，需先把 pytest 作为 dev 依赖装上。

**文件：**
- 修改：`pyproject.toml`
- 创建：`tests/conftest.py`
- 创建：`tests/__init__.py`（空）

- [ ] **步骤 1：在 pyproject.toml 增加 dev 依赖**

在 `pyproject.toml` 的 `[project.scripts]` 块**之前**插入：

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0,<9"]
```

- [ ] **步骤 2：创建 tests 包标记与 conftest**

创建 `tests/__init__.py`（空文件）。

创建 `tests/conftest.py`：

```python
"""pytest 配置：确保 src 布局可导入。"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
```

- [ ] **步骤 3：安装 dev 依赖**

运行：`. .venv/bin/activate && pip install -e '.[dev]'`
预期：成功安装 pytest。

- [ ] **步骤 4：验证 pytest 可运行**

运行：`. .venv/bin/activate && python -m pytest --version`
预期：打印 `pytest 8.x`。

- [ ] **步骤 5：Commit**

```bash
git add pyproject.toml tests/__init__.py tests/conftest.py
git commit -m "test: 引入 pytest 测试基础设施"
```

---

## 任务 2：digest 解析辅助函数（`_parse_float` / `_age_hours`）

先做最底层、纯函数、易测的两个辅助。

**文件：**
- 创建：`src/mteam_cli/api/digest.py`
- 测试：`tests/test_digest.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_digest.py`：

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`. .venv/bin/activate && python -m pytest tests/test_digest.py -v`
预期：FAIL（`ModuleNotFoundError: No module named 'mteam_cli.api.digest'`）

- [ ] **步骤 3：编写最少实现**

创建 `src/mteam_cli/api/digest.py`：

```python
"""高分新片摘要：复用 search API，本地按 IMDB + 发布时间过滤。

纯 HTTP（经由 api_post / search_torrents），不依赖 Playwright。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

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


def _parse_float(value: Any) -> float | None:
    """把评分字段转 float；空/非数字 → None。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
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
```

- [ ] **步骤 4：运行测试验证通过**

运行：`. .venv/bin/activate && python -m pytest tests/test_digest.py -v`
预期：4 个测试 PASS。

- [ ] **步骤 5：Commit**

```bash
git add src/mteam_cli/api/digest.py tests/test_digest.py
git commit -m "feat(digest): 评分/发布时间解析辅助函数"
```

---

## 任务 3：单条结果整形 `_shape`

**文件：**
- 修改：`src/mteam_cli/api/digest.py`
- 测试：`tests/test_digest.py`

- [ ] **步骤 1：追加失败的测试**

在 `tests/test_digest.py` 末尾追加：

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`. .venv/bin/activate && python -m pytest tests/test_digest.py -k shape -v`
预期：FAIL（`ImportError: cannot import name '_shape'`）

- [ ] **步骤 3：实现 `_shape`**

在 `src/mteam_cli/api/digest.py` 顶部 import 增加：

```python
from mteam_cli.api import humanize as hz
```

在文件末尾追加：

```python
def _shape(t: dict[str, Any], *, mode: str, imdb: float) -> dict[str, Any]:
    """把一条 search 结果整形为 digest 行。"""
    return {
        "id": t.get("id"),
        "title": t.get("smallDescr") or t.get("name"),
        "type": TYPE_LABELS.get(mode, mode),
        "imdb": imdb,
        "douban": t.get("doubanRating") or "-",
        "size": hz.naturalsize(t.get("size")),
        "createdDate": t.get("createdDate"),
    }
```

- [ ] **步骤 4：运行测试验证通过**

运行：`. .venv/bin/activate && python -m pytest tests/test_digest.py -v`
预期：全部 PASS（含前面 4 个）。

- [ ] **步骤 5：Commit**

```bash
git add src/mteam_cli/api/digest.py tests/test_digest.py
git commit -m "feat(digest): 单条结果整形 _shape"
```

---

## 任务 4：核心过滤 `fetch_high_score_digest`

**文件：**
- 修改：`src/mteam_cli/api/digest.py`
- 测试：`tests/test_digest.py`

- [ ] **步骤 1：追加失败的测试**

在 `tests/test_digest.py` 末尾追加（用 monkeypatch 替换 `search_torrents`，避免真实网络）：

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`. .venv/bin/activate && python -m pytest tests/test_digest.py -k fetch -v`
预期：FAIL（`AttributeError: module ... has no attribute 'fetch_high_score_digest'` 或 `search_torrents`）

- [ ] **步骤 3：实现 fetch + 模块级 import**

在 `src/mteam_cli/api/digest.py` 顶部 import 区追加（与现有 import 并列）：

```python
from mteam_cli.api.public import as_list, search_torrents
```

在文件末尾追加：

```python
async def fetch_high_score_digest(
    api_key: str,
    *,
    base_url: str,
    min_imdb: float,
    types: list[str],
    hours: int,
    limit: int,
    now: str | None = None,
) -> list[dict[str, Any]]:
    """拉取各类型最新结果，按 IMDB 阈值 + 发布时间窗过滤，降序截断。

    ``now`` 仅供测试注入。空关键词搜索取该类目最新；若生产不接受空关键词，
    在此改用宽泛词或 mode=normal 类目过滤（probe-verified during impl）。
    """
    rows: list[dict[str, Any]] = []
    for mode in types:
        data = await search_torrents(
            api_key, "", base_url=base_url, mode=mode, page_size=100
        )
        for t in as_list(data):
            imdb = _parse_float(t.get("imdbRating"))
            if imdb is None or imdb < min_imdb:
                continue
            age = _age_hours(t.get("createdDate"), now=now)
            if age is not None and age > hours:
                continue
            rows.append(_shape(t, mode=mode, imdb=imdb))
    rows.sort(key=lambda r: r["imdb"], reverse=True)
    return rows[:limit]
```

> 注：`search_torrents` 必须是**模块级名字**（`digest_mod.search_torrents`），测试才能 monkeypatch。故在 `digest.py` 顶部 `from ... import search_torrents`，调用时直接用 `search_torrents(...)`。

- [ ] **步骤 4：运行测试验证通过**

运行：`. .venv/bin/activate && python -m pytest tests/test_digest.py -v`
预期：全部 PASS。

- [ ] **步骤 5：Commit**

```bash
git add src/mteam_cli/api/digest.py tests/test_digest.py
git commit -m "feat(digest): 核心过滤 fetch_high_score_digest"
```

---

## 任务 5：通知文本格式化 `format_digest`

**文件：**
- 修改：`src/mteam_cli/api/digest.py`
- 测试：`tests/test_digest.py`

- [ ] **步骤 1：追加失败的测试**

在 `tests/test_digest.py` 末尾追加：

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`. .venv/bin/activate && python -m pytest tests/test_digest.py -k format -v`
预期：FAIL（`ImportError: cannot import name 'format_digest'`）

- [ ] **步骤 3：实现 `format_digest`**

在 `src/mteam_cli/api/digest.py` 末尾追加：

```python
def format_digest(rows: list[dict[str, Any]], *, min_imdb: float) -> str:
    """生成签到通知尾部的 digest 文本片段；空结果返回空串（整段省略）。"""
    if not rows:
        return ""
    lines = [f"📽 今日高分新片 (IMDB≥{min_imdb:g})"]
    for r in rows:
        lines.append(f"• [{r['imdb']:g}] {r['title']} ({r['type']})")
    return "\n".join(lines)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`. .venv/bin/activate && python -m pytest tests/test_digest.py -v`
预期：全部 PASS。

- [ ] **步骤 5：Commit**

```bash
git add src/mteam_cli/api/digest.py tests/test_digest.py
git commit -m "feat(digest): 通知文本格式化 format_digest"
```

---

## 任务 6：导出 digest 公共函数

**文件：**
- 修改：`src/mteam_cli/api/__init__.py`

- [ ] **步骤 1：在 __init__.py 增加导入与导出**

修改 `src/mteam_cli/api/__init__.py`：在 `from mteam_cli.api.session import ...` 之后追加：

```python
from mteam_cli.api.digest import fetch_high_score_digest, format_digest
```

并在 `__all__` 列表末尾（`"load_session",` 之后）追加：

```python
    "fetch_high_score_digest",
    "format_digest",
```

- [ ] **步骤 2：验证导入**

运行：`. .venv/bin/activate && python -c "from mteam_cli.api import fetch_high_score_digest, format_digest; print('ok')"`
预期：打印 `ok`。

- [ ] **步骤 3：Commit**

```bash
git add src/mteam_cli/api/__init__.py
git commit -m "feat(digest): 导出 digest 公共函数"
```

---

## 任务 7：配置解析（`Account.digest_enabled` + `Settings.digest_*`）

**文件：**
- 修改：`src/mteam_cli/core/config.py`
- 测试：`tests/test_config_digest.py`

参考现有结构：`Account` 是 `@dataclass(slots=True, frozen=True)`，已有 `telegram_token` 等字段与 `_suffixed(name, i)` 辅助；`Settings` 已有 `smtp_*` 全局字段与 `from_env()`；`_env_bool`/`_env_int` 已存在。

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_config_digest.py`：

```python
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
```

> 注：测试用 `importlib.reload` 是因为 `config.py` 在导入时执行 `load_dotenv()`；reload 确保 monkeypatch 的环境变量在 `from_env()` 读取时生效。`_reload_settings` 不依赖真实 `.env`（monkeypatch 的变量优先）。

- [ ] **步骤 2：运行测试验证失败**

运行：`. .venv/bin/activate && python -m pytest tests/test_config_digest.py -v`
预期：FAIL（`AttributeError: 'Account' object has no attribute 'digest_enabled'`）

- [ ] **步骤 3：增加 Account 字段**

在 `src/mteam_cli/core/config.py` 的 `Account` 数据类中，于 `smtp_to: str | None = None` 之后追加字段：

```python
    digest_enabled: bool = False
```

- [ ] **步骤 4：增加 Settings 字段**

在 `Settings` 数据类中，于 schedule 字段块之前（`schedule_window` 之上）追加：

```python
    # ── digest（高分新片摘要，全局参数）──
    digest_min_imdb: float = 8.0
    digest_types: list[str] = field(default_factory=lambda: ["movie", "tvshow"])
    digest_hours: int = 24
    digest_limit: int = 10
```

> `field` 已在文件顶部 `from dataclasses import dataclass, field` 导入（现有代码已用 `field(default_factory=list)`）。

- [ ] **步骤 5：在 from_env() 读取全局 digest 参数**

在 `Settings.from_env()` 的 `return cls(` 调用中，于 `smtp_use_tls=...` 之后、`schedule_window=...` 之前追加：

```python
            digest_min_imdb=float(os.getenv("MTEAM_DIGEST_MIN_IMDB", "8.0")),
            digest_types=[
                t.strip()
                for t in os.getenv("MTEAM_DIGEST_TYPES", "movie,tvshow").split(",")
                if t.strip()
            ],
            digest_hours=_env_int("MTEAM_DIGEST_HOURS", 24),
            digest_limit=_env_int("MTEAM_DIGEST_LIMIT", 10),
```

- [ ] **步骤 6：在 _parse_accounts() 读取账户开关**

在 `Settings._parse_accounts()` 内构造 `Account(...)` 的地方，于 `smtp_to=smtp_to,` 之后追加：

```python
                    digest_enabled=_env_bool(f"MTEAM_DIGEST_ENABLED_{i}", False),
```

> `_env_bool(name, default)` 已存在（读 env 并按 1/true/yes/on 判真）。确认它接受 `f"...{i}"` 动态名——它直接 `os.getenv(name)`，可以。

- [ ] **步骤 7：运行测试验证通过**

运行：`. .venv/bin/activate && python -m pytest tests/test_config_digest.py -v`
预期：4 个测试 PASS。

- [ ] **步骤 8：Commit**

```bash
git add src/mteam_cli/core/config.py tests/test_config_digest.py
git commit -m "feat(digest): 账户级开关 + 全局参数配置解析"
```

---

## 任务 8：`mteam-cli digest` 命令

**文件：**
- 创建：`src/mteam_cli/cli/commands/digest.py`
- 修改：`src/mteam_cli/cli/main.py`

参考 `cli/commands/search.py` 的结构与 `cli/_query.py` 的 `run`/`fetch`/`maybe_raw`。

- [ ] **步骤 1：创建命令模块**

创建 `src/mteam_cli/cli/commands/digest.py`：

```python
"""高分新片摘要预览命令（API key）。"""

from __future__ import annotations

import argparse
import logging

from mteam_cli.api import fetch_high_score_digest
from mteam_cli.cli._account import add_account_arg, require_query, resolve_account_or_exit
from mteam_cli.cli._emit import Field, add_format_arg, add_raw_arg, emit_rows, notice
from mteam_cli.cli._query import fetch, maybe_raw, run
from mteam_cli.core.config import Settings

_FIELDS = [
    Field("rank", "#"),
    Field("id", "ID"),
    Field("title", "标题"),
    Field("type", "类型"),
    Field("imdb", "IMDB"),
    Field("douban", "豆瓣"),
    Field("size", "大小"),
    Field("createdDate", "发布时间"),
]


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("digest", help="预览当天高分新片（IMDB 高分影视）。")
    p.add_argument("--min-imdb", type=float, default=None, help="IMDB 评分下限（默认取全局配置）")
    p.add_argument("--types", default=None, help="资源类型，逗号分隔（默认取全局配置）")
    p.add_argument("--hours", type=int, default=None, help="发布时间窗（小时，默认取全局配置）")
    p.add_argument("-n", "--limit", type=int, default=None, help="最多条数（默认取全局配置）")
    add_account_arg(p)
    add_format_arg(p)
    add_raw_arg(p)
    p.set_defaults(func=handle)


async def handle(
    args: argparse.Namespace, settings: Settings, logger: logging.Logger
) -> int:
    return await run(_run(args, settings))


async def _run(args: argparse.Namespace, settings: Settings) -> int:
    account = resolve_account_or_exit(args, settings)
    require_query(account)

    min_imdb = args.min_imdb if args.min_imdb is not None else settings.digest_min_imdb
    types = (
        [t.strip() for t in args.types.split(",") if t.strip()]
        if args.types
        else settings.digest_types
    )
    hours = args.hours if args.hours is not None else settings.digest_hours
    limit = args.limit if args.limit is not None else settings.digest_limit

    rows = await fetch(
        fetch_high_score_digest(
            account.api_key,
            base_url=settings.api_base_url,
            min_imdb=min_imdb,
            types=types,
            hours=hours,
            limit=limit,
        )
    )
    if maybe_raw(args, rows):
        return 0

    if not rows:
        notice(f"当天无 IMDB≥{min_imdb:g} 的新片。")
        return 0
    ranked = [{**r, "rank": i} for i, r in enumerate(rows, start=1)]
    emit_rows(ranked, _FIELDS, fmt=args.output_format)
    return 0
```

- [ ] **步骤 2：在 main.py 注册命令**

修改 `src/mteam_cli/cli/main.py`：在 `_COMMAND_MODULES` 元组中，数据查询区（`"notices",` 之后）追加：

```python
    "digest",
```

- [ ] **步骤 3：验证命令注册与解析**

运行：`. .venv/bin/activate && mteam-cli digest --help`
预期：打印 digest 命令帮助，含 `--min-imdb` / `--types` / `--hours` / `-n` / `-f` / `--raw`。

- [ ] **步骤 4：验证模块导入无误**

运行：`. .venv/bin/activate && python -c "import mteam_cli.cli.commands.digest; print('ok')"`
预期：打印 `ok`。

- [ ] **步骤 5：Commit**

```bash
git add src/mteam_cli/cli/commands/digest.py src/mteam_cli/cli/main.py
git commit -m "feat(digest): mteam-cli digest 预览命令"
```

---

## 任务 9：签到 runner 集成（fetch-once + 拼接）

**文件：**
- 修改：`src/mteam_cli/automation/runner.py`

当前 `run_one_account_tick(account, settings, logger)` 在签到成功后发 `body=result.profile_text`。需：① `run_all_accounts` 在循环前按需拉一次 digest；② 把 digest_text 传入并拼接到开了开关的账户通知。

- [ ] **步骤 1：给 run_one_account_tick 增加 digest_text 参数并拼接**

修改 `src/mteam_cli/automation/runner.py`：

把函数签名

```python
async def run_one_account_tick(
    account: Account,
    settings: Settings,
    logger: logging.Logger,
) -> CheckinResult:
```

改为：

```python
async def run_one_account_tick(
    account: Account,
    settings: Settings,
    logger: logging.Logger,
    digest_text: str = "",
) -> CheckinResult:
```

把通知正文那行

```python
            body=result.profile_text if result.ok else (result.error or "登录失败"),
```

改为：

```python
            body=_compose_body(result, account, digest_text),
```

- [ ] **步骤 2：增加 _compose_body 辅助**

在 `src/mteam_cli/automation/runner.py` 文件末尾追加：

```python
def _compose_body(result: CheckinResult, account: Account, digest_text: str) -> str:
    """签到通知正文：成功时为 profile；开了 digest 开关且有内容则拼接。"""
    if not result.ok:
        return result.error or "登录失败"
    body = result.profile_text
    if account.digest_enabled and digest_text:
        body = f"{body}\n\n{digest_text}"
    return body
```

- [ ] **步骤 3：在 run_all_accounts 里 fetch-once**

修改 `run_all_accounts`：在 `worst = 0` 之前插入 digest 拉取逻辑，并把 `digest_text` 传进每次 tick。

找到：

```python
    if not keepalive_targets:
        logger.warning("没有可保活的账户（需 user+pass+totp）。")
        return 0

    worst = 0
    for acct in keepalive_targets:
        try:
            result = await run_one_account_tick(acct, settings, logger)
```

替换为：

```python
    if not keepalive_targets:
        logger.warning("没有可保活的账户（需 user+pass+totp）。")
        return 0

    digest_text = await _maybe_fetch_digest(keepalive_targets, settings, logger)

    worst = 0
    for acct in keepalive_targets:
        try:
            result = await run_one_account_tick(acct, settings, logger, digest_text)
```

- [ ] **步骤 4：增加 _maybe_fetch_digest 辅助**

在 `src/mteam_cli/automation/runner.py` 文件末尾追加：

```python
async def _maybe_fetch_digest(
    targets: list[Account],
    settings: Settings,
    logger: logging.Logger,
) -> str:
    """若有账户开了 digest 开关，用第一个有 api_key 的账户拉一次并格式化。

    全站统一内容，只拉一次。任何失败只记日志、返回空串——绝不影响签到。
    """
    if not any(a.digest_enabled for a in targets):
        return ""
    fetcher = next((a for a in settings.accounts if a.can_query), None)
    if fetcher is None:
        logger.warning("digest 已开启但无可用 api_key 账户，跳过。")
        return ""
    try:
        from mteam_cli.api import fetch_high_score_digest, format_digest

        rows = await fetch_high_score_digest(
            fetcher.api_key,
            base_url=settings.api_base_url,
            min_imdb=settings.digest_min_imdb,
            types=settings.digest_types,
            hours=settings.digest_hours,
            limit=settings.digest_limit,
        )
        return format_digest(rows, min_imdb=settings.digest_min_imdb)
    except Exception:  # noqa: BLE001 — digest 失败绝不影响签到
        logger.exception("digest 拉取失败，本轮通知不含高分新片")
        return ""
```

> `Account` 已在文件顶部 `from mteam_cli.core.config import Account, Settings` 导入。

- [ ] **步骤 5：验证导入与编译**

运行：`. .venv/bin/activate && python -c "import mteam_cli.automation.runner; print('ok')"`
预期：打印 `ok`。

运行：`. .venv/bin/activate && python -m compileall -q src/mteam_cli`
预期：无输出（成功）。

- [ ] **步骤 6：Commit**

```bash
git add src/mteam_cli/automation/runner.py
git commit -m "feat(digest): 签到 runner 集成（fetch-once + 按开关拼接）"
```

---

## 任务 10：runner 集成单测

**文件：**
- 创建：`tests/test_runner_digest.py`

验证 `_compose_body` 的开关逻辑（纯函数，易测；`_maybe_fetch_digest` 涉及 async + 多依赖，由任务 9 的导入/编译校验 + 任务 11 的端到端覆盖）。

- [ ] **步骤 1：编写测试**

创建 `tests/test_runner_digest.py`：

```python
from mteam_cli.automation.runner import _compose_body
from mteam_cli.core.config import Account
from mteam_cli.core.models import CheckinResult


def _acct(digest_enabled):
    return Account(username="u", api_key="k", digest_enabled=digest_enabled)


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
```

> 注：`Account` 是 frozen dataclass，构造时只传必要字段，其余用默认值。确认 `CheckinResult` 字段名为 `ok`/`error`/`profile_text`（见 `core/models.py`）。

- [ ] **步骤 2：运行测试验证通过**

运行：`. .venv/bin/activate && python -m pytest tests/test_runner_digest.py -v`
预期：4 个测试 PASS。

- [ ] **步骤 3：运行全部测试**

运行：`. .venv/bin/activate && python -m pytest tests/ -v`
预期：所有测试 PASS。

- [ ] **步骤 4：Commit**

```bash
git add tests/test_runner_digest.py
git commit -m "test(digest): runner 拼接逻辑单测"
```

---

## 任务 11：配置文件与文档

**文件：**
- 修改：`.env.template`
- 修改：`docker-compose.yaml`
- 修改：`kubernetes-manifests/statefulset.yaml`
- 修改：`CLAUDE.md`
- 修改：`README.md`

- [ ] **步骤 1：.env.template 增加 digest 段**

在 `.env.template` 的 SMTP 段之后、schedule 段之前插入：

```ini
# ── 高分新片摘要（拼进签到通知；按账户开关）──────────────────
# 账户级开关（默认 false）：开启后该账户签到通知尾部附当天高分新片
# MTEAM_DIGEST_ENABLED_1=true

# IMDB 评分下限
MTEAM_DIGEST_MIN_IMDB=8.0
# 资源类型（search mode，逗号分隔）
# 可选: movie(电影) / tvshow(电视剧) / music(音乐) / adult(成人)
#        / waterfall(瀑布流) / rss / rankings(排行) / all(全部) / normal(综合)
# 注意: music/adult 等非影视类型没有 IMDB 评分，会被评分过滤滤光，不适合本功能。
MTEAM_DIGEST_TYPES=movie,tvshow
# 发布时间窗口（小时）
MTEAM_DIGEST_HOURS=24
# 最多列出条数
MTEAM_DIGEST_LIMIT=10
```

- [ ] **步骤 2：docker-compose.yaml 增加 env 示例**

在 `docker-compose.yaml` 的 environment 段，schedule 区之前插入：

```yaml
      # ── 高分新片摘要（按账户开关 + 全局参数）──
      # - MTEAM_DIGEST_ENABLED_1=true
      - MTEAM_DIGEST_MIN_IMDB=8.0
      - MTEAM_DIGEST_TYPES=movie,tvshow
      - MTEAM_DIGEST_HOURS=24
      - MTEAM_DIGEST_LIMIT=10
```

- [ ] **步骤 3：statefulset.yaml 增加 env 示例**

在 `kubernetes-manifests/statefulset.yaml` 的 env 列表，schedule 区之前插入：

```yaml
            # ── 高分新片摘要 ──
            # - name: MTEAM_DIGEST_ENABLED_1
            #   value: "true"
            - name: MTEAM_DIGEST_MIN_IMDB
              value: "8.0"
            - name: MTEAM_DIGEST_TYPES
              value: movie,tvshow
            - name: MTEAM_DIGEST_HOURS
              value: "24"
            - name: MTEAM_DIGEST_LIMIT
              value: "10"
```

- [ ] **步骤 4：README.md 增加命令说明**

在 `README.md` 数据查询命令清单中（`mteam-cli notices` 那一行之后）追加：

```bash
mteam-cli digest                       # 预览当天高分新片（IMDB 高分影视）
```

并在配置说明处补一句：「高分新片摘要：账户级开关 `MTEAM_DIGEST_ENABLED_<n>`（默认关），全局参数 `MTEAM_DIGEST_MIN_IMDB`/`_TYPES`/`_HOURS`/`_LIMIT`；开启后随签到通知发出。」

- [ ] **步骤 5：CLAUDE.md 增加架构说明**

在 `CLAUDE.md` 的 `api/` 小节末尾追加一行：

```markdown
- `digest.py` — 高分新片摘要：复用 `search_torrents` 拉 movie/tvshow，本地按 IMDB 阈值 + 发布时间窗过滤排序。`fetch_high_score_digest` + `format_digest`。供 `digest` 命令与签到 runner（fetch-once）共用。
```

并在命令清单（数据查询部分）补 `mteam-cli digest`。

- [ ] **步骤 6：验证 compose / k8s YAML 合法**

运行：`. .venv/bin/activate && python -c "import yaml; yaml.safe_load(open('docker-compose.yaml')); yaml.safe_load(open('kubernetes-manifests/statefulset.yaml')); print('yaml ok')"`
预期：打印 `yaml ok`。

- [ ] **步骤 7：Commit**

```bash
git add .env.template docker-compose.yaml kubernetes-manifests/statefulset.yaml README.md CLAUDE.md
git commit -m "docs(digest): 配置示例与文档"
```

---

## 任务 12：端到端验证（真实 API，用户环境）

> ⚠️ 此任务需在能访问 M-Team 的网络上运行（开发沙箱被 Cloudflare 拦截）。由用户执行或在 Pod 内执行。

- [ ] **步骤 1：探测空关键词搜索行为**

运行：`. .venv/bin/activate && mteam-cli digest --hours 168 --min-imdb 7.0 -n 5`
预期：返回最近一周 IMDB≥7 的影视若干条。
**若报错或返回空**：说明 `search_torrents(keyword="")` 不被生产接受。修复点在 `api/digest.py` 的 `fetch_high_score_digest`——把空关键词改为 `mode=normal` + 类目过滤，或用宽泛关键词。修完重跑本步。

- [ ] **步骤 2：验证 JSON 输出 pipe-clean**

运行：`mteam-cli digest -n 3 -f json | python -c "import sys,json; print(len(json.load(sys.stdin)))"`
预期：打印条数，无报错（确认错误/空提示走 stderr）。

- [ ] **步骤 3：验证签到集成**

临时在 `.env` 设 `MTEAM_DIGEST_ENABLED_1=true`，运行 `mteam-cli run --account <name>`。
预期：该账户签到通知正文尾部出现「📽 今日高分新片」段（若当天有高分新片）。

- [ ] **步骤 4：记录探测结论**

若步骤 1 需要调整 search 调用方式，更新 `api/digest.py` 注释说明生产实际接受的参数形态，并 commit。

---

## 自检结果

**1. 规格覆盖度**（对照 spec 各节）：
- 数据源 search API → 任务 4 ✓
- fetch-once → 任务 9 `_maybe_fetch_digest` ✓
- 账户级开关 + 全局参数 → 任务 7 ✓
- 过滤细节（IMDB/时间窗/排序/截断/不去重/解析失败保留）→ 任务 2/4 ✓
- `mteam-cli digest` 命令 → 任务 8 ✓
- 通知格式 + 空结果整段省略 → 任务 5 + 任务 9 `_compose_body` ✓
- 配置示例含类型备注 → 任务 11 ✓
- 受影响文件全覆盖 → 任务 1-11 ✓
- 测试（解析/过滤/格式/配置/拼接 + 端到端探测空关键词）→ 任务 2-10 + 12 ✓

**2. 占位符扫描**：无 TODO/待定。"probe-verified during impl" 出现在任务 4 注释与任务 12——这是项目既定纪律（生产 API 形态需实测），且任务 12 给了明确的修复指引与位置，非模糊占位。

**3. 类型一致性**：
- `_shape(t, *, mode, imdb)` 定义（任务 3）与调用（任务 4）一致。
- `fetch_high_score_digest(api_key, *, base_url, min_imdb, types, hours, limit, now=None)` 定义（任务 4）与命令调用（任务 8，不传 now）、runner 调用（任务 9，不传 now）一致。
- `format_digest(rows, *, min_imdb)` 定义（任务 5）与调用（任务 9）一致。
- `_compose_body(result, account, digest_text)` 定义（任务 9）与测试（任务 10）一致。
- `Account.digest_enabled` / `Settings.digest_min_imdb`/`digest_types`/`digest_hours`/`digest_limit` 定义（任务 7）与使用（任务 8/9）一致。
- `search_torrents` 在 digest.py 为模块级名字，monkeypatch 目标一致（任务 4 注明）。
