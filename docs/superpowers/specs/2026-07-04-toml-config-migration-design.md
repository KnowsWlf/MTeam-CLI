# 配置迁移：扁平环境变量 → TOML（混合式，env 可覆盖密钥）

**日期：** 2026-07-04
**状态：** 设计
**目标版本：** 0.6.0

---

## 1. 问题陈述

当前配置是**扁平的、带数字后缀的环境变量**，由 `.env` 经 python-dotenv 载入。多账户支持是「biggest divergence」（CLAUDE.md 自述），表达力问题在运行一段时间后显现：

### 1.1 具体痛点（逐条对上代码）

| 痛点 | 现状（`core/config.py`） | 后果 |
|---|---|---|
| **账户不是一个「单元」** | 账户 2 的 13 个字段散落在 13 个 `_2` 后缀变量里 | 改/删一个账户要全文搜 `_2`；心智上账户不内聚 |
| **一切皆字符串** | `_env_bool` / `_env_int` / `_suffixed_int` / `_suffixed_float` / 逗号 split / `_coalesce` 全在补偿这一点 | 一整组解析辅助函数只为把字符串还原成 bool/int/float/list |
| **三级优先级不可见** | `MTEAM_DIGEST_MIN_SEEDERS`（全局）vs `..._1`（账户覆盖）谁盖谁全靠脑补 | 配置意图不在结构里，只在文档和代码里 |
| **连续编号是地雷** | `_parse_accounts` 循环：第一个 `username` 且 `api_key` 都空就 `break` | 删掉账户 2 会**静默丢掉**账户 3+；这是隐蔽的正确性陷阱 |
| **通知 per-account × per-channel** | 4 个通知字段 × N 账户全部扁平化 | 变量数随账户线性膨胀 |

### 1.2 为什么 TOML 恰好解决

TOML 原生支持 **table 数组**（`[[account]]`）、**嵌套 table**（`[account.digest]`）、**原生类型**（bool/int/float/array）。这几点正好一一消除上表的偶发复杂度——不是锦上添花，是移除已有的 scaffolding。

---

## 2. 目标与非目标

### 目标
1. 配置主来源改为 **TOML 文件**（默认 `config.toml`，gitignored）。
2. 账户成为结构化单元（`[[account]]`），digest 全局默认 + 账户覆盖用嵌套 table 表达。
3. **密钥仍可用 env 覆盖**（混合式）：任一密钥字段若存在对应 env 变量，则 env 优先。保证 CI/k8s 可只注入密钥、不把明文烤进镜像。
4. 值对象（`Account` / `Settings` / `DigestConfig`）**零改动**——只替换解析层。
5. 删除现在只为补偿「扁平字符串」而存在的解析辅助。
6. 三级优先级（命令行 > 账户覆盖 > 全局默认）语义**完全不变**。

### 非目标
- 不改任何下游消费者（`runner` / `cli` / `notify` / `api` / `scheduler`）——它们只认值对象。
- 不改 digest 的合并规则、信号逻辑、通知逻辑。
- 不引入新的第三方依赖（用 3.11+ 标准库 `tomllib`）。
- 不做配置热重载、不做 schema 校验框架（YAGNI）。

---

## 3. 设计

### 3.1 文件格式（`config.toml`）

```toml
# ── 全局基础设施 ──
[site]
base_url = "https://zp.m-team.io"
api_base_url = "https://api.m-team.cc/api"
headless = true
timeout_ms = 60000

[schedule]
window = "09:00-11:00"
pre_delay_range = "10-300"
heartbeat_hours = 1

# ── SMTP 服务器（全局；收件人在每个账户里）──
[smtp]
host = "smtp.qq.com"
port = 465
user = "me@qq.com"
password = "授权码"
from = "me@qq.com"          # 纯邮箱，勿带显示名（否则 QQ 502）
use_tls = true

# ── digest 全局默认 ──
[digest]
min_imdb = 8.0
min_seeders = 30
types = ["movie", "tvshow"]
hours = 24
limit = 10

# ── 账户（数组，每个块一个账户）──
[[account]]
username = "Bytewild"
password = "..."
totp_secret = "..."
api_key = "019e887a-..."
digest_enabled = true
  [account.notify]
  telegram_token = ""
  telegram_chat_id = ""
  feishu_token = ""
  smtp_to = "me@foxmail.com"
  [account.digest]            # 只写想覆盖的键；其余继承 [digest]
  types = ["music"]
  min_seeders = 50

[[account]]
username = "riddd"
api_key = "..."               # data-only 账户，合法
```

**映射表（TOML 键 → 值对象字段）：**

| TOML | 值对象 |
|---|---|
| `[site].base_url` / `.api_base_url` / `.headless` / `.timeout_ms` / `.slow_mo_ms` | `Settings.base_url` / … |
| `[site].auth_dir` / `.log_dir` / `.artifact_dir`（可选，默认 `data/*`）| `Settings.auth_dir` / … |
| `[schedule].window` / `.pre_delay_range` / `.heartbeat_hours` | `Settings.schedule_*` |
| `[smtp].host` / `.port` / `.user` / `.password` / `.from` / `.use_tls` | `Settings.smtp_*` |
| `[digest].min_imdb` / `.min_seeders` / `.types` / `.hours` / `.limit` | `Settings.digest_*` |
| `[[account]].username` / `.password` / `.totp_secret` / `.api_key` / `.digest_enabled` | `Account.*` |
| `[account.notify].telegram_token` / `.telegram_chat_id` / `.feishu_token` / `.smtp_to` | `Account.telegram_token` / … |
| `[account.digest].types` / `.min_imdb` / `.hours` / `.limit` / `.min_seeders` | `Account.digest_*`（可空覆盖）|

### 3.2 混合式：env 覆盖密钥

**规则：** TOML 提供基础值；对**密钥字段**，若存在对应 env 变量则 env 优先。作用域限定在密钥（避免把整套 env 逻辑又搬回来）。

覆盖清单（env 名保持与今天一致，向后兼容 CI/k8s 现有注入）：

| 字段 | env 覆盖名 |
|---|---|
| 账户 i 的 `password` | `MTEAM_PASSWORD_i` |
| 账户 i 的 `totp_secret` | `MTEAM_TOTP_SECRET_i` |
| 账户 i 的 `api_key` | `MTEAM_API_KEY_i` |
| `[smtp].password` | `NOTIFY_SMTP_PASSWORD` |

> `i` = 账户在数组中的 1-based 序号（与 TOML 顺序一致）。**账户身份由 TOML 决定**，env 只覆盖既有账户的密钥，不能新增账户——这是有意的：结构在文件里，密钥可外部注入。

**优先级：** env 覆盖 > TOML 值。空/未设 env 不覆盖（用 `None` 语义，非空串判断，保持与现有 `_suffixed` 一致的「空即不设」）。

### 3.3 文件位置与发现

`Settings.from_toml(path=None)`：
1. 显式 `path` 参数（测试/`--config` 用）。
2. env `MTEAM_CONFIG`（部署指定路径）。
3. 默认 `ROOT_DIR / "config.toml"`。

找不到文件 → 清晰报错（指向 `config.toml.template`），除非纯 env 场景（见 3.4）。

### 3.4 迁移与兼容策略

**决策点（见 §6 需用户确认）：** 是否保留 `from_env` 作为回退？

- **方案 A（推荐，干净切换）：** 移除 `from_env`，只认 TOML（密钥仍可 env 覆盖）。提供 `config.toml.template` + 一段 `.env → config.toml` 对照文档。旧 `.env` 用户需一次性迁移。
- **方案 B（双读回退）：** 无 `config.toml` 时回退到 `from_env`。兼容性好但**保留了要淘汰的扁平逻辑**，与「移除 scaffolding」的目标冲突，且双路径要双份测试。

倾向 A：这是个人多账户工具、单一部署者（你），一次性迁移成本低，回退路径的长期维护成本更高。

### 3.5 解析层结构（`config.py` 改动）

```python
import tomllib

def _load_toml(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)

def _env_secret(name: str) -> str | None:
    raw = os.getenv(name)
    return raw.strip() if raw and raw.strip() else None
    # password 不 strip（与现有 MTEAM_PASSWORD_i 行为一致）——见实现注意

@classmethod
def from_toml(cls, path: Path | None = None) -> "Settings":
    data = _load_toml(_resolve_config_path(path))
    site = data.get("site", {})
    digest = data.get("digest", {})
    ...
    accounts = cls._parse_accounts_toml(data.get("account", []))
    return cls(...)

@staticmethod
def _parse_accounts_toml(items: list[dict]) -> list[Account]:
    accounts = []
    for i, a in enumerate(items, start=1):
        notify = a.get("notify", {})
        adigest = a.get("digest", {})
        accounts.append(Account(
            username=a["username"],
            password=_env_secret(f"MTEAM_PASSWORD_{i}") or a.get("password") or None,
            totp_secret=_env_secret(f"MTEAM_TOTP_SECRET_{i}") or a.get("totp_secret"),
            api_key=_env_secret(f"MTEAM_API_KEY_{i}") or a.get("api_key"),
            telegram_token=notify.get("telegram_token") or None,
            ...
            digest_types=adigest.get("types"),          # 原生 list，无需 split
            digest_min_imdb=adigest.get("min_imdb"),    # 原生 float，无需 _suffixed_float
            digest_hours=adigest.get("hours"),
            digest_limit=adigest.get("limit"),
            digest_min_seeders=adigest.get("min_seeders"),
        ))
    return accounts
```

**可删除的辅助**（迁移后无调用者）：`_env_bool` / `_env_int` / `_suffixed` / `_suffixed_int` / `_suffixed_float`。`_coalesce` **保留**（`resolved_digest_config` 仍用它，值对象不动）。

> 注意：TOML 的 `adigest.get("min_imdb")` 缺键返回 `None`，正好是「继承全局」语义，无需 `_coalesce` 在解析层——合并仍在 `resolved_digest_config`（唯一来源，不变）。

### 3.6 doctor / 报错文案

- `doctor` 打印的「未配置账户」「MTEAM_USERNAME_1」等提示需改为指向 TOML（`config.toml` / `[[account]]`）。
- `Account.ensure_keepalive` / `ensure_query` / `Settings.resolve_account` 的报错文案改为 TOML 术语。

---

## 4. 影响文件清单

| 文件 | 改动 | 风险 |
|---|---|---|
| `core/config.py` | 加 `from_toml` / `_parse_accounts_toml` / `_load_toml` / `_env_secret` / `_resolve_config_path`；删 5 个 env 辅助；改报错文案 | 中（核心） |
| `cli/main.py` | `Settings.from_env()` → `Settings.from_toml()`（唯一生产调用点） | 低 |
| `cli/commands/doctor.py` | 配置提示文案改 TOML | 低 |
| `config.toml.template`（新增）| 替代 `.env.template` | — |
| `.env.template` | 删除（或保留一段「已迁移至 TOML」说明 + 密钥 env 覆盖清单） | 低 |
| `pyproject.toml` | 移除 `python-dotenv` 依赖；版本 0.5.x → 0.6.0 | 低 |
| `CLAUDE.md` | 「Configuration」整段重写为 TOML | 低（文档）|
| `README.md` | 配置章节改 TOML | 低（文档）|
| `Dockerfile` / `docker-compose.yaml` / `k8s statefulset` | `.env` 挂载 → `config.toml` 挂载；密钥仍可 env/Secret 注入 | 中（部署）|
| `tests/test_config_*.py` | env-reload 模式 → 写临时 TOML 文件（`tmp_path`）| 中（测试重写）|
| `tests/test_runner_digest.py` / `test_digest_command.py` | 若依赖 `from_env`，改为构造 `Settings` 或临时 TOML | 低 |

**爆炸半径小**：生产只有 1 处 `from_env` 调用点；值对象与全部下游不动。

---

## 5. 测试策略

- **解析层单测**（新 `test_config_toml.py`）：用 `tmp_path` 写临时 TOML，断言值对象字段。覆盖：
  - 全局默认全继承 / 账户部分覆盖 / 全覆盖 / 零值不被吞（`min_imdb=0.0` / `limit=0` / `min_seeders=0`）
  - 多账户独立、data-only 账户、keepalive-only 账户
  - env 密钥覆盖（TOML 有值 → env 盖过；env 空 → 用 TOML）
  - 缺文件报错、缺 `username` 报错
  - `resolved_digest_config` 三级合并（复用现有断言，只换构造方式）
- **回归**：现有 `test_config_digest.py` 的语义用例全部平移到 TOML 构造，行为断言不变。
- **全量 pytest** 绿。
- **手工冒烟**：`doctor` + 一条 data 命令（`digest --types music`）在真实 `config.toml` 下跑通。

---

## 6. 已确认决策（2026-07-04）

1. **兼容策略：方案 A —— 干净切换，移除 `from_env`。** 只认 TOML（密钥仍可 env 覆盖）。删掉整套扁平解析辅助，无双路径。提供 `config.toml.template` + `.env → config.toml` 对照文档，旧用户一次性迁移。
2. **文件发现：`config.toml`（仓库根，gitignored）+ 三级发现。** 优先级：`--config PATH` 命令行参数 > `MTEAM_CONFIG` env > 默认 `ROOT_DIR/config.toml`。`--config` 加为**全局参数**（在 `main.py` 的顶层 parser，`func` 分发前解析），所有子命令共享。
3. **部署密钥：ConfigMap + env/Secret 注入。** `config.toml` 的非密钥部分走 ConfigMap 挂载；密钥（`password`/`totp_secret`/`api_key`/`smtp.password`）走 env / k8s Secret 注入，由混合式 §3.2 覆盖。明文不入镜像、不入 ConfigMap。符合 12-factor。
   - **实现要点：** ConfigMap 里的 `config.toml` 密钥字段可留空串或占位；env 覆盖生效。`_env_secret` 的「空即不设」保证空 ConfigMap 值 + env 注入 = 用 env。

### 6.1 `--config` 全局参数落点

`main.py:build_parser()` 顶层加 `parser.add_argument("--config", type=Path, default=None)`；`main()` 里 `Settings.from_toml(args.config)`。子命令 parser 不受影响（`--config` 在子命令名之前解析）。

---

## 7. 版本

新配置格式是面向用户的 breaking change（`.env` → `config.toml`）→ **0.6.0**（minor，前 1.0 阶段 breaking 走 minor）。发布须在 CLAUDE.md/README 显著标注迁移说明。
```
