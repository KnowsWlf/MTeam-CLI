# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`mteam-cli` is a layered async CLI for the M-Team private tracker, with two faces:

- 🤖 **Keep-alive automation** — daily multi-account browser login (M-Team deletes accounts after 40 days of inactivity). Login is fully automatic via TOTP; there is **no QR / no human-in-the-loop**.
- 🧠 **AI-friendly data source** — profile/stats, torrent search/detail, seeding/leeching + H&R, messages/notices, emitted as clean structured data (`table`/`json`/`yaml`/`csv`/`md`/`plain`) for piping to `jq` / feeding an LLM / wrapping as an Agent tool.

It was refactored from a single-file script (now removed); the login logic was ported faithfully and verified live.

## Commands

```bash
# Install (Python ≥3.11)
python -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install chromium          # only needed for keep-alive (login/run/schedule/inspect)

cp config.toml.template config.toml && $EDITOR config.toml

# ── automation / diagnostics ──
mteam-cli doctor                     # sync self-check; no playwright/pyotp/api imports
mteam-cli login   [--account NAME]   # one-shot browser login (password+TOTP), saves localStorage
mteam-cli run     [--account NAME]   # one keep-alive tick (default: ALL keep-alive accounts)
mteam-cli schedule                   # long-running, one daily job per account (container default)
mteam-cli inspect [--login]          # dump login-page artifacts when the DOM changes

# ── data queries (API key; --account defaults to first; -f/--format) ──
mteam-cli profile [--account NAME]
mteam-cli search <keyword> [-n N] [--mode M] [--category C ...]
mteam-cli detail <id> [--dl-token]
mteam-cli seeding [--leeching] [-n N]
mteam-cli hnr [-n N]
mteam-cli messages [-n N]
mteam-cli notices [-n N]
mteam-cli digest [--account NAME]

# `python -m mteam_cli <cmd>` is equivalent to `mteam-cli <cmd>`.
```

`-f json|yaml|csv` is **pipe-clean** (no banner/footer; logs go to stderr). There is no test suite or linter configured.

## Configuration (TOML, `config.toml` via stdlib `tomllib`)

**配置是 TOML 文件**（不是环境变量）。发现顺序：`--config PATH`（顶层全局参数）> `MTEAM_CONFIG` env > `ROOT_DIR/config.toml`。解析层唯一入口 `Settings.from_toml(path)`，生产只在 `cli/main.py` 调一次。见 `config.toml.template`。

**结构**（每个账户是 `[[account]]` 数组的一个块，不再是扁平 `_i` 后缀）：
- 全局 table：`[site]`（base_url/api_base_url/headless/timeout_ms）、`[schedule]`（window/pre_delay_range/heartbeat_hours）、`[smtp]`（host/port/user/password/from/use_tls，服务器全局共享）、`[digest]`（min_imdb/min_seeders/types/hours/limit，全局默认）。
- `[[account]]`：`username`（= 账户名，`--account <username>`）、`password`、`totp_secret`、`api_key`、`digest_enabled`。凭证独立：user+pass+totp → `can_keepalive`；api_key → `can_query`。data-only 或 keepalive-only 账户都合法。
  - `[account.notify]`：`telegram_token`+`telegram_chat_id`、`feishu_token`、`smtp_to`（各渠道 opt-in）。→ `Account.has_telegram`/`has_smtp`/`has_feishu`。
  - `[account.digest]`：可选覆盖 `types`/`min_imdb`/`hours`/`limit`/`min_seeders`；缺键 → `None` → 继承 `[digest]`（合并在 `resolved_digest_config`）。

**混合式：密钥可用 env 覆盖**（便于 CI/k8s 注入、明文不入镜像/ConfigMap）。`_env_secret(name)` 读取，「空即不设」（空串不算覆盖），env 非空则盖过 TOML：
- 账户 i（1-based，按 TOML 数组顺序）：`MTEAM_PASSWORD_i` / `MTEAM_TOTP_SECRET_i` / `MTEAM_API_KEY_i`
- 全局：`NOTIFY_SMTP_PASSWORD`
- env 只覆盖既有账户的密钥，**不能新增账户**（结构在 TOML，密钥可外部注入）。

原生 TOML 类型（bool/int/float/array）免去了旧 env 方案的 `_env_bool`/`_suffixed*`/split 一整套辅助——它们已删除。`_coalesce` 保留（`resolved_digest_config` 仍用，保 `0.0`/`0` 不被吞）。命令用 `ensure_keepalive`/`ensure_query` 在缺凭证时清晰退出。

> Note: 配置方案历经两次演进——legacy 单账户 env → 编号 `_i` 多账户 env → **TOML（0.6.0）**。旧 `.env`/`from_env`/扁平解析已移除；迁移见 `config.toml.template`。**SMTP `from` 仍须纯邮箱地址**（见 Critical constraints）。

## Architecture

```
src/mteam_cli/
  ├── core/         Settings (multi-account) + logging + models + BrowserSession (trimmed)
  ├── api/          M-Team data API: pure HTTP via x-api-key (NO Playwright)
  ├── automation/   browser keep-alive: localstorage + login + runner
  ├── notify/       Telegram + SMTP + Feishu, built PER-ACCOUNT (NotifierHub: concurrent + error-isolated)
  ├── scheduler/    DailyScheduler (one job per account)
  └── cli/          argparse dispatcher + per-command modules + emit/table/account helpers
```

**The two faces are strictly separated.** Data commands (`api/` + their command modules) never import Playwright — they call `api.api_post(...)` over urllib, authed either by the account's `api_key` (most endpoints) or by the web-session JWT read from the localStorage snapshot (`hnr`/`messages`; see `api/session.py`). Keep-alive commands (`automation/` + `core/browser.py`) own all the Playwright code. This keeps `doctor` and every data command usable where Chromium isn't installed.

### `core/`
- `config.py` — **`Account`** value object (`safe_name`, `storage_path`, `can_keepalive`, `can_query`, `resolved_digest_config`) + **`Settings`** with `accounts: list[Account]`, `from_toml(path)` (TOML parse + env 密钥覆盖via `_env_secret`), `resolve_account(name)` (None → first). `_parse_accounts_toml` reads the `[[account]]` array. This multi-account `Settings` is the biggest divergence from a single-tenant design.
- `browser.py` — trimmed `BrowserSession`: launch + context + navigation + `snapshot()`. **No state-machine detection, no storage_state injection** (auth lives in localStorage; see `automation/localstorage.py`).
- `models.py` — `ActionResult`, `CheckinResult`, `SnapshotBundle`.

### `api/` (data — pure HTTP)
Verified against M-Team's OpenAPI spec (`https://test2.m-team.cc/api/swagger-ui/`, `/api/v3/api-docs`) + a live envelope probe.
- `_internal.py` — **`api_post(path, *, base_url, api_key=None, auth_token=None, did=None, visitorid=None, params=None, body=None, form=None)`**: every endpoint is **POST**. Auth is either `api_key` → `x-api-key`, or `auth_token` → `authorization` (the web-session JWT, with `did`/`visitorid`; api_key omitted). `params` → query string; `form` → urlencoded; `body` → JSON. Unwraps the `{code, message, data}` envelope where **`code == 0` (int) is success**; raises `MTeamAuthError` on 401/403 or an auth-looking `message` (`key無效`/`無許可權`/`Full authentication`), `MTeamAPIError` otherwise.
- `public.py` — thin per-endpoint wrappers + `get_own_uid` + `as_list`. Endpoint map: `profile` `/member/profile?uid` (omit uid → self), `search` body `/torrent/search` (`pageNumber`/`pageSize`/`keyword`/`mode`), `detail` form `/torrent/detail` (`id`), `gen_dl_token` form `/torrent/genDlToken` (`id`), `seeding` body `/member/getUserTorrentList` (`userid`+`type` SEEDING/LEECHING/COMPLETED, `pageNumber`), `hnr` `/member/getCrimeRecords?uid` (**JWT**), `messages` body `/msg/search` (**JWT**), `notices` `/system/news`.
- `session.py` — `load_session(storage_path) → WebSession`: reads the JWT from the localStorage snapshot's `auth` key (+ `did`/`visitorId`, + `uid` decoded from the JWT). `hnr`/`messages` use this because the API key is rejected (`無許可權` / `401`) on those endpoints.
  - **Known wall**: with the JWT (+ `webversion`/`ts`/`did`/`visitorid` headers) those endpoints pass auth + version checks but then return **`簽名錯誤`** — they require the SPA's client-side request signature `_sgin`, which we deliberately do **not** reverse-engineer (anti-automation, brittle, low value). So `hnr`/`messages` are effectively **web-UI-only**; they degrade to a clear "启用请求签名，CLI 不支持" message. The JWT plumbing is kept (it's generic and documents how far the session path gets). Don't add a signing implementation.
- **Host**: default `api.m-team.cc` (the working `mcp-server-mteam` reference uses `.cc`; `api.m-team.io` is a mirror, override via `MTEAM_API_BASE_URL`). Both sit behind Cloudflare, which **bot-blocks datacenter IPs** (302 → google.com) — so data commands must run from a normal/residential network, not a cloud sandbox. The search shape (`pageNumber`, JSON) and detail/genDlToken (form `id`) are taken from that proven reference, so they match production; the OpenAPI test server used `page` and differs.
- `humanize.py` — `naturalsize(binary=True)` / `ratio` / `num` formatting.
- `digest.py` — 高分/热门新片摘要：复用 `search_torrents` 拉各类型最新，本地按**类型对应的质量信号** + 发布时间窗过滤排序。`fetch_high_score_digest` + `format_digest`。供 `digest` 命令与签到 runner 共用。
  - **按类型信号（内置映射 `_IMDB_TYPES`）**：`movie`/`tvshow` 有 `imdbRating` → 用 `min_imdb` 阈值；其余（`music`/`adult`/…）没有 IMDB（生产实测 `imdbRating` 恒 None）→ 用 `status.seeders`（做种数=热度）≥ `min_seeders`。两信号尺度不可比，故**分桶排序**：imdb 组按评分降序在前、seeders 组按做种降序在后，再整体截 `limit`（纯影视配置行为与旧版一致）。`adult` 需账户在 M-Team 设置开启成人浏览权限，否则 search 返回 0 条。
  - **每账户隔离**：每个开了 `MTEAM_DIGEST_ENABLED_i` 的账户用自己的 api_key + 自己解析出的 `DigestConfig` 独立拉取（不全站共享）。配置三级优先级：命令行 > 账户覆盖 `MTEAM_DIGEST_*_i` > 全局默认 `MTEAM_DIGEST_*`，合并规则收敛在 `Account.resolved_digest_config(settings)`（唯一来源）。`_coalesce`（非 `or`）保 `min_imdb=0.0`/`limit=0`/`min_seeders=0` 不被吞。digest 拉取失败只记日志、签到照常——**digest 永不影响保活**。

### `automation/` (keep-alive — browser)
- `localstorage.py` — `LocalStorageManager` (load/save a page's localStorage to the per-account JSON file). M-Team stores its JWT in localStorage, so this — not Playwright `storage_state` — is the persistence mechanism (proven in the legacy script; do not "upgrade" it blindly).
- `login.py` — `perform_login(session, account, settings, logger)`: localStorage-first → password+TOTP fallback, confirmed by intercepting the `/api/member/profile` XHR and matching `data.username` with URL on `/index`. Handles the **three 2FA variants** (direct redirect / `#otp-code` input / `button:has-text("確認")`). **The login DOM selectors live here — update them (via `inspect`) when M-Team changes the login page.**
- `runner.py` — `run_one_account_tick` (builds that account's own hub via `build_notifier_hub(account, logger)`, then notifies through it) + `run_all_accounts` (loop, **failures isolated per account**). Single source shared by `run` + `schedule`. No `SESSION_EXPIRED`/exit-78 (no human-in-loop).

### `scheduler/`
`DailyScheduler.loop()` arms **one daily job per keep-alive account**, each at its own random HH:MM inside the window, plus in-tick jitter. Exceptions are logged but never crash the loop; hourly heartbeat for `docker logs` liveness. Each tick spawns its own `asyncio.run`.

### `cli/`
- `main.py` — discovers `_COMMAND_MODULES`, calls each module's `register(subparsers)`, routes `args.func`. Sync commands declare `IS_ASYNC = False` (`doctor`, `schedule`) and get `handle(args, settings)`; async get `handle(args, settings, logger)`.
- `_account.py` — `add_account_arg` + `resolve_account_or_exit` + `require_query`/`require_keepalive` guards.
- `_emit.py`/`_table.py` — multi-format renderer (`emit_rows`/`emit_record`/`auto_fields`) + CJK-width table. `auto_fields` derives columns from response keys so shape-unconfirmed commands still surface real data.
- `_browser.py` — `browser_session_ctx`: start a `BrowserSession`, always close (no detection/trace).

## Critical constraints (do not "optimize" away)

- **Keep-alive MUST stay browser-login.** The 40-day inactivity rule is reset by a real login, not by API-key access. Never replace the `automation/login.py` flow with an `api_post` ping — accounts would silently die.
- **Data ≠ keep-alive identity.** Data commands use `api_key`; keep-alive uses browser session. Don't entangle the two transports.
- **M-Team API shapes are probe-verified.** When an endpoint differs from `api/public.py`'s current assumption (path/method/body/`code`/fields), fix it there — never spread the assumption into command modules. Re-probe by capturing the SPA's real XHR (DevTools / `page.route`).
- **localStorage, not storage_state**, is the auth persistence format for M-Team.
- **`[smtp].from` must be a bare email address** (e.g. `user@foxmail.com`), NOT `DisplayName <addr>`. The code wraps it into `"MTeam-CLI <{sender}>"` for the From header; if sender already contains a display name, the double-wrapped result (e.g. `MTeam-CLI <MTeam-CLI<addr>>`) is syntactically invalid. smtplib can't extract a clean envelope address, and QQ/Foxmail SMTP returns `502 Invalid paramenters`. This was discovered the hard way: the dev-machine config had a bare address (works); the deployed config had a display-name value (502). The symptom on a dev machine with a working config is invisible — test in the real deployment environment.

## Deployment

- `Dockerfile` builds on `mcr.microsoft.com/playwright/python` (Chromium + zh-CN fonts), `pip install -e .`, `CMD ["mteam-cli","schedule"]`, `TZ=Asia/Shanghai` (so `schedule` reads HH:MM as Beijing time).
- `docker-compose.yaml` — single service, `mteam-data` named volume for `/app/data` (per-account localStorage snapshots + logs). Pin via `MTEAM_IMAGE_TAG`.
- k8s uses a **StatefulSet** (`kubernetes-manifests/statefulset.yaml`) with `volumeClaimTemplates` — login state is stateful + single-owner. No `Service` object (no ports).
- Per-account `data/auth/mteam_<safe_username>.json` carries live session tokens — **treat as credentials** (gitignored).
