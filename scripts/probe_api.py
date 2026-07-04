"""Live probe: log in with real creds and capture M-Team's real API shapes.

Drives the actual keep-alive login (reusing automation.login.perform_login),
recording every request/response to *m-team.io/api/* — method, path, the auth
header used (x-api-key vs Authorization bearer), request body, and the response
envelope structure. Then best-effort visits a few SPA routes to trigger more
endpoints (search, messages, ...).

Reads creds from env so it works regardless of .env format:
    MTEAM_PROBE_USERNAME / MTEAM_PROBE_PASSWORD / MTEAM_PROBE_TOTP

Usage:
    python scripts/probe_api.py
Writes a summary to data/artifacts/probe-api.json and prints it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from mteam_cli.automation.login import perform_login
from mteam_cli.core.browser import BrowserSession
from mteam_cli.core.config import Account, Settings

_ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("probe")

_AUTH_HEADER_KEYS = ("authorization", "x-api-key", "cookie")


def _shape(value: Any, depth: int = 0) -> Any:
    """Summarize a JSON value's structure (keys/types), not its data."""
    if depth > 3:
        return "…"
    if isinstance(value, dict):
        return {k: _shape(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return [_shape(value[0], depth + 1)] if value else []
    return type(value).__name__


async def main() -> int:
    # Prefer explicit probe vars; fall back to legacy single-account names so
    # an existing old-format .env works as-is, then to numbered _1 vars.
    username = (
        os.getenv("MTEAM_PROBE_USERNAME")
        or os.getenv("MTEAM_USERNAME")
        or os.getenv("MTEAM_USERNAME_1")
    )
    password = (
        os.getenv("MTEAM_PROBE_PASSWORD")
        or os.getenv("MTEAM_PASSWORD")
        or os.getenv("MTEAM_PASSWORD_1")
    )
    totp = (
        os.getenv("MTEAM_PROBE_TOTP")
        or os.getenv("MTEAM_TOTP_SECRET")
        or os.getenv("MTEAM_TOTP_SECRET_1")
    )
    if not (username and password and totp):
        print("缺少用户名/密码/TOTP（MTEAM_PROBE_* 或 MTEAM_USERNAME/PASSWORD/TOTP_SECRET）")
        return 2

    # 探测脚本自行从 env 取凭证（上方），Settings 仅供 base_url/目录等基础设施，
    # 故用默认值直接构造（不依赖 config.toml）。
    settings = Settings(
        base_url=os.getenv("MTEAM_BASE_URL", "https://zp.m-team.io").rstrip("/"),
        api_base_url=os.getenv("MTEAM_API_BASE_URL", "https://api.m-team.cc/api").rstrip("/"),
        headless=os.getenv("MTEAM_HEADLESS", "true").lower() in {"1", "true", "yes", "on"},
        slow_mo_ms=0,
        timeout_ms=int(os.getenv("MTEAM_TIMEOUT_MS", "60000")),
        auth_dir=_ROOT / "data/auth",
        log_dir=_ROOT / "data/logs",
        artifact_dir=_ROOT / "data/artifacts",
    )
    settings.ensure_directories()
    account = Account(username=username, password=password, totp_secret=totp)

    captured: list[dict[str, Any]] = []

    session = BrowserSession(settings, logger)
    await session.start(headless=True)
    page = session.page

    async def on_response(response) -> None:
        url = response.url
        if "m-team.io/api" not in url:
            return
        req = response.request
        entry: dict[str, Any] = {
            "method": req.method,
            "url": url.split("?")[0],
            "query": url.split("?")[1] if "?" in url else "",
            "status": response.status,
        }
        try:
            headers = await req.all_headers()
            entry["auth_headers"] = {
                k: (v[:24] + "…" if len(v) > 24 else v)
                for k, v in headers.items()
                if k.lower() in _AUTH_HEADER_KEYS
            }
        except Exception:
            entry["auth_headers"] = {}
        try:
            entry["post_data"] = req.post_data
        except Exception:
            entry["post_data"] = None
        try:
            body = await response.json()
            entry["resp_shape"] = _shape(body)
            if isinstance(body, dict):
                entry["code"] = body.get("code")
                entry["message"] = body.get("message")
        except Exception:
            entry["resp_shape"] = "(non-json)"
        captured.append(entry)
        logger.info("captured %s %s -> %s", entry["method"], entry["url"], entry["status"])

    page.on("response", lambda r: asyncio.create_task(on_response(r)))

    # 1) The real login (triggers /member/profile).
    result = await perform_login(session, account, settings, logger)
    logger.info("login ok=%s err=%s", result.ok, result.error)

    # 2) Best-effort: visit SPA routes to trigger more endpoints.
    for route in ("/index", "/browse", "/msgbox", "/member/profile", "/torrent"):
        try:
            await page.goto(f"{settings.base_url}{route}", timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=15000)
            await page.wait_for_timeout(2000)
        except Exception as exc:
            logger.info("route %s skipped: %s", route, exc)

    await session.close()

    # Dedupe by (method, url).
    seen: dict[tuple, dict] = {}
    for e in captured:
        seen[(e["method"], e["url"])] = e
    summary = sorted(seen.values(), key=lambda e: e["url"])

    out = settings.artifact_dir / "probe-api.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== 捕获到 {len(summary)} 个去重端点，写入 {out} ===")
    for e in summary:
        print(f"\n{e['method']} {e['url']}  (status={e['status']}, code={e.get('code')})")
        print(f"  auth: {e.get('auth_headers')}")
        if e.get("post_data"):
            print(f"  body: {e['post_data'][:200]}")
        print(f"  resp: {json.dumps(e.get('resp_shape'), ensure_ascii=False)[:600]}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
