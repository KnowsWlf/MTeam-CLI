# 高分新片摘要 · 每账户隔离重构 — 设计文档

**日期:** 2026-06-21
**版本目标:** 0.3.2 → 0.4.0（行为变更 + 新配置面，按 minor）
**前序设计:** [2026-06-05-high-score-digest-design.md](./2026-06-05-high-score-digest-design.md)（首版「全站共用一次拉取」）

## 背景与动机

首版 digest 采用「全站共用一次拉取」：`run_all_accounts` 用第一个有 api_key 的账户、按全局参数拉一次，所有账户共享同一份文本，再由 `_compose_body` 按每账户 `digest_enabled` 决定是否拼接。

这套「拉一次 + 共享 + 两道开关判断 + tick 内兜底补拉」的逻辑产生了一个生产问题：`mteam-cli run --account Bytewild`（单账户路径）通知含 digest，而 `mteam-cli run`（全账户路径）不含——两条路径对同一份共享文本的处理产生了分叉。

本次重构把 digest 改为**每账户完全隔离**：每个账户用自己的 api_key、自己的配置，独立拉取自己的 digest。

### 设计决策（已与用户确认）

1. **隔离粒度：完全隔离。** 每账户独立拉取，不再共享。
2. **配置模型：方案 C（全局默认 + 账户可选覆盖）。** 全局 `MTEAM_DIGEST_*` 降级为默认值；每账户可用 `MTEAM_DIGEST_*_i` 选择性覆盖任意维度，未覆盖的继承全局。
3. **覆盖建模：方案 2（`DigestConfig` 值对象 + `Account.resolved_digest_config` 方法）。** 「覆盖 then 继承」的合并规则收敛在一个方法里，作为单一来源。
4. **本次范围：仅隔离重构。** music/adult 的非 imdb 过滤（方案 B）留作未来方向，记入文末。

### 主动放弃的优化

首版「全站拉一次」的初衷是省 search 请求。本次**主动放弃**：N 个开了 digest 的账户每天拉 N 次。代价是每日一次保活时多几次 search 调用（可忽略），换来逻辑直线化 + 上述 bug 从结构上根除。用户已确认此取舍。

---

## 架构

### 1. 新增值对象 `DigestConfig`（`core/config.py`）

```python
@dataclass(slots=True, frozen=True)
class DigestConfig:
    types: list[str]
    min_imdb: float
    hours: int
    limit: int
```

不可变，承载一个账户**解析后**的最终 digest 参数。

### 2. `Account` 扩展（`core/config.py`）

新增 4 个可空覆盖字段（`None` = 继承全局）+ 1 个解析方法：

```python
class Account:
    digest_enabled: bool = False                  # 已有
    digest_types: list[str] | None = None         # 新增
    digest_min_imdb: float | None = None          # 新增
    digest_hours: int | None = None               # 新增
    digest_limit: int | None = None               # 新增

    def resolved_digest_config(self, settings: "Settings") -> DigestConfig:
        return DigestConfig(
            types=self.digest_types or settings.digest_types,
            min_imdb=_coalesce(self.digest_min_imdb, settings.digest_min_imdb),
            hours=_coalesce(self.digest_hours, settings.digest_hours),
            limit=_coalesce(self.digest_limit, settings.digest_limit),
        )
```

**`_coalesce(a, b) = a if a is not None else b`**（模块级辅助）。
不能用 `a or b`：`min_imdb=0.0` / `limit=0` 是合法值，`or` 会把它们当假值吞掉。
`types` 用 `or` 是安全的——空列表继承全局正是期望行为。

### 3. env 解析（`core/config.py` 的 `_parse_accounts`）

每账户 `_i` 新增（全部可选，不配 → `None` → 继承全局）：

| 变量 | 类型 | 不配时 |
|---|---|---|
| `MTEAM_DIGEST_ENABLED_i` | bool | `False`（已有） |
| `MTEAM_DIGEST_TYPES_i` | 逗号分隔 | `None` → 继承 `MTEAM_DIGEST_TYPES` |
| `MTEAM_DIGEST_MIN_IMDB_i` | float | `None` → 继承全局 |
| `MTEAM_DIGEST_HOURS_i` | int | `None` → 继承全局 |
| `MTEAM_DIGEST_LIMIT_i` | int | `None` → 继承全局 |

新增两个解析辅助（现有 `_env_int`/`_env_bool` 总返回非空，不可复用）：

```python
def _suffixed_int(name: str, i: int) -> int | None     # 没配或空白 → None
def _suffixed_float(name: str, i: int) -> float | None
# types 复用现有 _suffixed + split，空 → None
```

**向后兼容：** 全局 `MTEAM_DIGEST_MIN_IMDB`/`TYPES`/`HOURS`/`LIMIT` 原样保留，角色从「唯一配置」变为「默认值」。现有生产配置（全局 4 参数 + `MTEAM_DIGEST_ENABLED_1=true`）零改动继续按原意工作——账户继承全局参数，只是改从自己的 api_key 拉取。

### 4. 运行流改造（`automation/runner.py`）

**改造前**（共享文本，三处判断）：

```
run_all_accounts:
    digest_text = _maybe_fetch_digest(keepalive_targets)   # 预拉一次
    for acct in keepalive_targets:
        run_one_account_tick(acct, digest_text)            # 共享
            if not digest_text and acct.digest_enabled and ok:  # tick 内兜底补拉
                digest_text = _maybe_fetch_digest([acct])
            _compose_body: if acct.digest_enabled and digest_text: 拼接  # 二次开关
```

**改造后**（每账户自包含，一处拼接）：

```
run_all_accounts:
    for acct in keepalive_targets:
        run_one_account_tick(acct)                  # 不再传 digest_text
            result = perform_login(...)
            digest_text = ""
            if acct.digest_enabled and result.ok and acct.can_query:
                cfg = acct.resolved_digest_config(settings)
                digest_text = await _fetch_digest_for(acct, cfg, settings, logger)
            body = _compose_body(result, digest_text)   # 一处拼接，无二次开关
```

**净删除：**
- `_maybe_fetch_digest`（整个函数）
- `run_one_account_tick` 的 `digest_text` 参数 + tick 内兜底补拉分支
- `_compose_body` 的 `digest_enabled` 二次判断（改为只看 `digest_text` 是否非空）
- `run_all_accounts` 的预拉取两行
- 排查期临时加的调试日志

**新增：**
- `_fetch_digest_for(account, cfg, settings, logger)`：用 `account.api_key` + `cfg` 拉取并格式化，try/except 兜底（失败只记日志、返回空串，绝不影响签到）。每账户一行正式日志 `[user] digest: 命中 N 条` / `[user] digest: 未开启`。

**关键变化：** 每账户用**自己的 api_key** 拉取，digest 内容随该账户 cfg 而变。一个账户只配 movie、另一个继承 movie+tvshow，互不影响。

### 5. 命令层（`cli/commands/digest.py`）

`digest` 预览命令改为消费同一个 `resolved_digest_config`，与 `run` 路径统一配置来源（行为不再可能漂移）。CLI 显式 `--min-imdb` 等仍可临时覆盖，形成**三级优先级：命令行 > 账户 > 全局**。

```python
cfg = account.resolved_digest_config(settings)
min_imdb = args.min_imdb if args.min_imdb is not None else cfg.min_imdb
types = (split(args.types) if args.types else cfg.types)
hours = args.hours if args.hours is not None else cfg.hours
limit = args.limit if args.limit is not None else cfg.limit
```

### 6. `api/digest.py`

`fetch_high_score_digest` 签名**不变**（仍接收散参数 `min_imdb`/`types`/`hours`/`limit`）。调用方从 `DigestConfig` 解包传入即可。纯函数无需改动，17 个现有测试继续保护。

---

## 数据流

```
.env (全局 MTEAM_DIGEST_* + 账户 MTEAM_DIGEST_*_i)
   ↓ Settings.from_env / _parse_accounts
Settings(全局默认) + Account(可空覆盖字段)
   ↓ account.resolved_digest_config(settings)   ← 合并规则唯一来源
DigestConfig(types, min_imdb, hours, limit)
   ↓ 解包
fetch_high_score_digest(account.api_key, **cfg)
   ↓
format_digest → digest_text → _compose_body → 通知
```

两条消费路径（`run` 的 runner、`digest` 命令）汇聚到同一个 `resolved_digest_config`。

---

## 错误处理

- digest 拉取失败：`_fetch_digest_for` 内 try/except，记日志、返回空串，签到通知照常发出（不含高分新片）。**digest 永不影响保活。**
- 账户开了 `digest_enabled` 但无 api_key（`can_query=False`）：跳过拉取，记一行日志，不报错。
- `min_imdb=0.0` / `limit=0`：通过 `_coalesce`（而非 `or`）正确保留，不被当假值吞掉。

---

## 测试

- **`test_digest.py`（17 例纯函数）：** 不动。
- **`test_config_digest.py`：** 新增 `resolved_digest_config` 用例——
  - 全空覆盖 → 完全继承全局
  - 部分账户覆盖（如只覆盖 `types`）→ 该维度用账户值，其余继承
  - `min_imdb=0.0` 覆盖 → 不被 `or` 吞掉（回归保护）
  - `_suffixed_int`/`_suffixed_float` 空值 → `None`
- **`test_runner_digest.py`：** 删掉 `_compose_body`/`_maybe_fetch_digest` 旧用例；新增——
  - 每账户用自己的 cfg 拉取（两账户不同 types，各拉各的）
  - 账户 `digest_enabled=False` → 不拉、通知无 digest
  - 拉取抛异常 → 签到通知照常发出
- **`test_api_internal.py`（17 例）：** 不动。

---

## 文档收尾

- `.env.template`：增补每账户 `MTEAM_DIGEST_*_i` 示例 + 三级继承说明。
- `CLAUDE.md`：digest 段更新为「每账户隔离」，删去「全站拉一次」描述。

---

## 方案 B：非 imdb 质量信号（0.5.0 已实现）

> 首版标为「未来方向」，0.5.0 落地。先**探测了真实字段**（CLAUDE.md 原则）再写码。

**探测结论（生产 `api.m-team.cc`，music 10 条样本）：**
- `imdbRating` / `doubanRating` —— **恒为 None**，IMDB/豆瓣对 music 完全无效。
- `status.seeders` —— **有值**（字符串数字，如 `"326"`），做种数=站内热度硬指标。
- `status.timesCompleted` —— 有值（累计完成数，备选信号，未采用）。
- `createdDate` —— 有值且降序，时间窗过滤照常可用。
- `adult` —— 空/带词均返回 0 条：测试账户未开成人浏览权限；字段结构与 music 同源。

**实现：** digest 按类型选信号（内置映射 `_IMDB_TYPES={movie,tvshow}`）——影视用 `min_imdb`，其余用 `status.seeders ≥ min_seeders`。两信号尺度不可比，**分桶排序**（imdb 组降序在前、seeders 组降序在后）再截 `limit`，纯影视配置行为与 0.4.0 一致。`format_digest` 对 seeders 行用 🌱 前缀。新配置 `MTEAM_DIGEST_MIN_SEEDERS`（全局默认 30 + `_i` 覆盖），并入 `DigestConfig`/`resolved_digest_config`。

**未采用的备选：** `timesCompleted`（偏向老种）、`doubanRating`（music 也为 None）。`seeders` 是当前热度的直接信号，最契合「新片精选」。

---

## 影响文件清单

| 文件 | 改动 |
|---|---|
| `core/config.py` | +`DigestConfig`、+`_coalesce`、+`_suffixed_int/float`、`Account` +4 字段 +`resolved_digest_config`、`_parse_accounts` 读新 env |
| `automation/runner.py` | 删 `_maybe_fetch_digest`、改 `run_one_account_tick`/`run_all_accounts`/`_compose_body`、+`_fetch_digest_for` |
| `cli/commands/digest.py` | 改用 `resolved_digest_config`，三级优先级 |
| `tests/test_config_digest.py` | +覆盖/继承用例 |
| `tests/test_runner_digest.py` | 删旧共享用例、+每账户隔离用例 |
| `.env.template` | +每账户 digest 覆盖示例 |
| `CLAUDE.md` | digest 段更新 |
| `pyproject.toml` / `__init__.py` | 0.3.2 → 0.4.0 |
