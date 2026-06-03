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

cp .env.template .env && $EDITOR .env

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

# `python -m mteam_cli <cmd>` is equivalent to `mteam-cli <cmd>`.
```

`-f json|yaml|csv` is **pipe-clean** (no banner/footer; logs go to stderr). There is no test suite or linter configured.

## Configuration (env, loaded from `.env` via python-dotenv)

**Everything is per-account — there is NO global config except infra (paths, schedule, base URLs).** Accounts come from numbered vars starting at `_1`, contiguous. The account **name = its username** (`--account <username>`).

Per account `_i`:
- Credentials (independent sets): `MTEAM_USERNAME_i` + `MTEAM_PASSWORD_i` + `MTEAM_TOTP_SECRET_i` → `can_keepalive`; `MTEAM_API_KEY_i` → `can_query`.
- **Notify, also per-account** (each channel opts in on its own vars): `NOTIFY_TELEGRAM_TOKEN_i`+`NOTIFY_TELEGRAM_CHAT_ID_i`, `NOTIFY_FEISHU_TOKEN_i`, `NOTIFY_SMTP_HOST_i`/`_PORT_i`/`_USER_i`/`_PASSWORD_i`/`_FROM_i`/`_TO_i`/`_USE_TLS_i` (`NOTIFY_EMAIL_i` is accepted as an alias for `NOTIFY_SMTP_TO_i`). Exposed as `Account.has_telegram` / `has_smtp` / `has_feishu`.

An api-key-only account is valid (data-only); a password+totp-only account is valid (keep-alive-only). The parser stops at the first index with neither username nor api_key. Commands call `require_keepalive` / `require_query` and exit clearly when the needed credential is missing.

Global infra only: `MTEAM_BASE_URL`, `MTEAM_API_BASE_URL`, `MTEAM_HEADLESS`, `MTEAM_TIMEOUT_MS`, `MTEAM_SCHEDULE_WINDOW` (`09:00-11:00`), `MTEAM_SCHEDULE_PRE_DELAY_RANGE` (`10-300`), `MTEAM_SCHEDULE_HEARTBEAT_HOURS`.

> Note: the env scheme changed from the legacy script (single-account `MTEAM_USERNAME`, global `TELEGRAM_BOT_TOKEN`/`SMTP_HOST`/`NOTIFY_TYPE`). The new scheme is strictly numbered multi-account, **including notify**. See `.env.template`.

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
- `config.py` — **`Account`** value object (`safe_name`, `storage_path`, `can_keepalive`, `can_query`) + **`Settings`** with `accounts: list[Account]`, `from_env()` (numbered parse), `resolve_account(name)` (None → first). This multi-account `Settings` is the biggest divergence from a single-tenant design.
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

## Deployment

- `Dockerfile` builds on `mcr.microsoft.com/playwright/python` (Chromium + zh-CN fonts), `pip install -e .`, `CMD ["mteam-cli","schedule"]`, `TZ=Asia/Shanghai` (so `schedule` reads HH:MM as Beijing time).
- `docker-compose.yaml` — single service, `mteam-data` named volume for `/app/data` (per-account localStorage snapshots + logs). Pin via `MTEAM_IMAGE_TAG`.
- k8s uses a **StatefulSet** (`kubernetes-manifests/statefulset.yaml`) with `volumeClaimTemplates` — login state is stateful + single-owner. No `Service` object (no ports).
- Per-account `data/auth/mteam_<safe_username>.json` carries live session tokens — **treat as credentials** (gitignored).
