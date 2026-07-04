# 实现计划：配置迁移 env → TOML（0.6.0）

**设计文档：** `docs/superpowers/specs/2026-07-04-toml-config-migration-design.md`
**分支：** `feat/toml-config`
**方式：** TDD，每任务一提交，值对象不动、只换解析层。

决策已定：干净切换（删 `from_env`）；`config.toml` + `--config` + `MTEAM_CONFIG`；k8s ConfigMap + env/Secret 注入密钥。

---

## 任务序列

### 任务 1：TOML 解析核心 `from_toml` + `_parse_accounts_toml`

**测试先行**（新 `tests/test_config_toml.py`，用 `tmp_path` 写临时 TOML）：
- `test_from_toml_minimal`：只有一个 data-only 账户（`username`+`api_key`）→ 值对象正确。
- `test_from_toml_full_account`：全字段账户（保活+查询+notify+digest 覆盖）→ 每字段对上。
- `test_global_digest_defaults`：`[digest]` 全局值进 `Settings.digest_*`；缺省用硬编码默认。
- `test_account_digest_override_partial`：`[account.digest]` 只写 `types` → 其余继承全局（经 `resolved_digest_config`）。
- `test_zero_values_not_swallowed`：`[account.digest]` `min_imdb=0.0` / `limit=0` / `min_seeders=0` → 不被吞。
- `test_multi_account_independent`：两账户不同 digest.types → 各自独立。
- `test_smtp_global`：`[smtp]` → `Settings.smtp_*`。
- `test_site_and_schedule`：`[site]` / `[schedule]` → 对应字段；缺省用默认。

**实现**：`config.py` 加 `tomllib` import、`_load_toml`、`_resolve_config_path`、`from_toml`、`_parse_accounts_toml`。此步**先不删** `from_env`（避免测试断裂），只新增。值对象与 `resolved_digest_config` 不动。

**验收**：新测试全绿；现有测试仍绿（`from_env` 尚在）。

---

### 任务 2：混合式 env 密钥覆盖

**测试先行**（`test_config_toml.py` 追加，`monkeypatch.setenv`）：
- `test_env_overrides_api_key`：TOML 有 `api_key="A"` + env `MTEAM_API_KEY_1="B"` → 用 `B`。
- `test_env_overrides_password_totp`：同理 `MTEAM_PASSWORD_1` / `MTEAM_TOTP_SECRET_1`。
- `test_env_overrides_smtp_password`：`NOTIFY_SMTP_PASSWORD` 盖 `[smtp].password`。
- `test_empty_env_does_not_override`：env 设为空串 → 仍用 TOML 值（「空即不设」）。
- `test_env_index_matches_toml_order`：账户 2 的密钥用 `_2` 后缀，按数组序号。

**实现**：`_env_secret(name)` + 在 `_parse_accounts_toml` 里对 4 类密钥应用 `_env_secret(...) or toml_value`。注意 `password` 的 strip 行为与旧 `MTEAM_PASSWORD_i`（不 strip）一致——在实现注释里标明抉择。

**验收**：覆盖用例绿；其余绿。

---

### 任务 3：`--config` 全局参数 + 三级发现

**测试先行**：
- `test_resolve_config_path_explicit`：显式 path 优先。
- `test_resolve_config_path_env`：`MTEAM_CONFIG` 次之。
- `test_resolve_config_path_default`：都无 → `ROOT_DIR/config.toml`。
- `test_missing_file_errors`：路径不存在 → 清晰 `SystemExit`（提示 `config.toml.template`）。

**实现**：`_resolve_config_path(path)` 三级；`main.py` 顶层 parser 加 `--config`，`main()` 传入 `from_toml(args.config)`。

**验收**：路径发现用例绿；`mteam-cli --config X doctor` 冒烟通。

---

### 任务 4：切换生产入口 + 删 `from_env` 及扁平辅助

**实现**（此步是「干净切换」）：
- `main.py`：`Settings.from_env()` → `Settings.from_toml(args.config)`（唯一生产调用点）。
- 删 `from_env`、`_parse_accounts`（旧）、`_env_bool`、`_env_int`、`_suffixed`、`_suffixed_int`、`_suffixed_float`。
- 删 python-dotenv import 块（顶部 try/except load_dotenv）。
- `_coalesce` 保留（`resolved_digest_config` 仍用）。

**测试迁移**：
- `test_config_digest.py`：`_reload_settings(env)` 模式 → 改为写临时 TOML 的 `_settings_from_toml(tmp_path, ...)`；行为断言全部不变（平移）。
- `test_runner_digest.py` / `test_digest_command.py`：若用 `Settings.from_env()`，改为直接构造 `Settings(...)` 或临时 TOML。

**验收**：全量 pytest 绿；无 `from_env` / `_suffixed*` 残留（grep 确认）。

---

### 任务 5：doctor + 报错文案改 TOML

**实现**：
- `doctor.py`：配置提示改指 `config.toml` / `[[account]]`。
- `Account.ensure_keepalive` / `ensure_query`、`Settings.resolve_account` 的报错文案改 TOML 术语。

**测试**：若 doctor 有测试则更新断言；否则手工冒烟 `mteam-cli doctor`。

**验收**：`doctor` 输出术语一致；无 `MTEAM_USERNAME_1` 之类旧提示残留。

---

### 任务 6：模板 + 依赖 + 文档 + 部署 + 版本 0.6.0

**实现**：
- 新增 `config.toml.template`（对照设计 §3.1，含注释：密钥可 env 覆盖、SMTP from 纯邮箱坑、adult 权限、三级优先级）。
- 删 `.env.template`（或替换为一页「已迁移至 TOML + 密钥 env 覆盖清单 + .env→toml 对照表」）。
- `pyproject.toml`：移除 `python-dotenv` 依赖；版本 → `0.6.0`。`src/mteam_cli/__init__.py` → `0.6.0`。
- `.gitignore`：加 `config.toml`（确认 `.env` 条目保留或调整）。
- `Dockerfile` / `docker-compose.yaml` / `k8s statefulset.yaml`：`.env` 挂载 → `config.toml`；k8s 用 ConfigMap（非密钥）+ Secret/env（密钥）。附 k8s ConfigMap + Secret 示例片段。
- `CLAUDE.md`「Configuration」整段重写为 TOML（保留所有关键约束：per-account、三级优先级、SMTP from 坑、digest 信号）。
- `README.md` 配置章节改 TOML。

**验收**：全量 pytest 绿；`doctor` + 一条 data 命令在真实 `config.toml` 下冒烟通；grep 无 `.env`/`dotenv`/`MTEAM_USERNAME_1` 于生产代码残留（部署密钥注入的 env 名保留是预期）。

---

## 收尾

全部 6 任务后：
1. 最终 code-review 子代理（或 `/brooks-review`）扫描 diff。
2. `finishing-a-development-branch`：合并 `feat/toml-config` → main、打 `v0.6.0` tag（单 tag 推）。
3. 发布须显著标注 **breaking change：`.env` → `config.toml` 迁移指引**。

## 风险与回退
- 爆炸半径小：生产仅 `main.py` 一处调用点，值对象与全部下游不动。
- 每任务独立提交，可 `git revert` 单步回退。
- 任务 1–3 只增不删（`from_env` 尚在），任务 4 才切换——切换前新路径已被测试覆盖。
