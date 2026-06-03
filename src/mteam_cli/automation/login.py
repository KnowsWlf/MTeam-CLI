"""Keep-alive browser login for one account.

Preserves the proven login logic from the original script:
  1. Try restoring the per-account localStorage snapshot (skips 2FA).
  2. Fall back to username + password + TOTP, handling the three observed
     2FA variants (direct redirect / #otp-code input / "確認" button).
  3. Confirm success by intercepting the ``/api/member/profile`` XHR and
     matching ``data.username`` against the configured account, with the URL
     landed on ``/index``. On success the localStorage snapshot is saved.

TOTP makes this fully automatic — there is no QR / human-in-the-loop.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pyotp
from playwright.async_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from mteam_cli.automation.localstorage import LocalStorageManager
from mteam_cli.core.browser import BrowserSession
from mteam_cli.core.config import Account, Settings
from mteam_cli.core.models import CheckinResult

_PROFILE_ENDPOINT = "/api/member/profile"


class _LoginAborted(Exception):
    """Internal: a login strategy did not achieve an authenticated session."""


async def perform_login(
    session: BrowserSession,
    account: Account,
    settings: Settings,
    logger: logging.Logger,
) -> CheckinResult:
    """Run the full keep-alive login for ``account`` and return its outcome."""
    page = session.page
    if page is None:
        raise RuntimeError("Browser session has not been started.")

    index_url = f"{settings.base_url}/index"
    login_url = f"{settings.base_url}/login"
    storage_file = str(account.storage_path(settings.auth_dir))

    # Shared holder populated by the intercepted profile XHR.
    profile: dict[str, Any] = {}

    async def _intercept(route, request) -> None:
        if request.url.endswith(_PROFILE_ENDPOINT):
            logger.info("[%s] 命中 profile 请求: %s", account.username, request.url)
            try:
                response = await route.fetch()
                profile.clear()
                profile.update(await response.json())
                await route.continue_()
                return
            except (ValueError, PlaywrightError) as exc:
                logger.warning("[%s] 读取 profile 响应出错: %s", account.username, exc)
        await route.continue_()

    await page.route(f"**{_PROFILE_ENDPOINT}", _intercept)
    logger.info("[%s] 已设置 profile 请求拦截", account.username)

    lsm = LocalStorageManager(page)

    try:
        await session.goto(f"{settings.base_url}/")

        def _logged_in() -> bool:
            data = profile.get("data") if profile else None
            return bool(
                page.url == index_url
                and data
                and data.get("username") == account.username
            )

        # ── Strategy 1: localStorage ──
        try:
            await _login_by_localstorage(
                page, lsm, storage_file, account, settings, logger, _logged_in
            )
        except _LoginAborted:
            logger.warning("[%s] LocalStorage 登录失败，改用账号密码", account.username)
            await _login_by_password(
                page, lsm, storage_file, login_url, index_url, account, settings, logger, _logged_in
            )

        text = _parse_profile(profile, account)
        logger.info("[%s] 登录成功", account.username)
        return CheckinResult(username=account.username, ok=True, profile_text=text)

    except _LoginAborted as exc:
        logger.error("[%s] 登录失败: %s", account.username, exc)
        return CheckinResult(username=account.username, ok=False, error=str(exc) or "登录失败")
    except PlaywrightError as exc:
        logger.error("[%s] 登录时发生 Playwright 错误: %s", account.username, exc)
        return CheckinResult(username=account.username, ok=False, error=f"Playwright 错误: {exc}")
    finally:
        try:
            await page.unroute(f"**{_PROFILE_ENDPOINT}")
        except PlaywrightError:
            pass


async def _login_by_localstorage(
    page: Page,
    lsm: LocalStorageManager,
    storage_file: str,
    account: Account,
    settings: Settings,
    logger: logging.Logger,
    logged_in,
) -> None:
    logger.info("[%s] 尝试通过 LocalStorage 登录", account.username)
    if not Path(storage_file).exists():
        raise _LoginAborted("无 LocalStorage 快照")
    try:
        await lsm.load_from_file(storage_file)
        await page.reload(timeout=settings.timeout_ms)
        await page.wait_for_load_state("networkidle", timeout=settings.timeout_ms)
        # Give the SPA time to fire its profile XHR (matches legacy behavior).
        await page.wait_for_timeout(timeout=min(settings.timeout_ms, 60_000))
    except PlaywrightError as exc:
        raise _LoginAborted(f"LocalStorage 登录出错: {exc}") from exc

    if logged_in():
        await lsm.save_to_file(storage_file)
        logger.info("[%s] LocalStorage 登录成功，已刷新快照", account.username)
        return
    raise _LoginAborted("LocalStorage 登录未确认")


async def _login_by_password(
    page: Page,
    lsm: LocalStorageManager,
    storage_file: str,
    login_url: str,
    index_url: str,
    account: Account,
    settings: Settings,
    logger: logging.Logger,
    logged_in,
) -> None:
    logger.info("[%s] 尝试通过账号密码登录", account.username)
    try:
        if page.url != login_url:
            await page.goto(login_url, timeout=settings.timeout_ms)
        await page.wait_for_load_state("networkidle", timeout=settings.timeout_ms)

        await page.locator('button[type="submit"]').wait_for(timeout=settings.timeout_ms)
        await page.locator('input[id="username"]').fill(account.username)
        await page.locator('input[id="password"]').fill(account.password or "")
        await page.locator('button[type="submit"]').click()

        await _handle_2fa(page, index_url, account, settings, logger)
    except PlaywrightError as exc:
        raise _LoginAborted(f"账号密码登录出错: {exc}") from exc

    if logged_in():
        await lsm.save_to_file(storage_file)
        logger.info("[%s] 账号密码登录成功，已保存快照", account.username)
        return
    raise _LoginAborted("账号密码登录未确认")


async def _handle_2fa(
    page: Page,
    index_url: str,
    account: Account,
    settings: Settings,
    logger: logging.Logger,
) -> None:
    """Handle the three observed 2FA variants after submitting credentials."""
    try:
        await page.wait_for_url(index_url, timeout=15_000)
        logger.info("[%s] 登录直接成功，无需 2FA", account.username)
        return
    except PlaywrightTimeoutError:
        pass

    otp_input = page.locator('input[id="otp-code"]')
    try:
        if await otp_input.count() > 0 and await otp_input.is_visible():
            code = pyotp.TOTP(account.totp_secret).now()
            await otp_input.fill(code)
            await page.locator('button[type="submit"]').click()
            await page.wait_for_url(index_url, timeout=30_000)
            return

        confirm_btn = page.locator('button:has-text("確認")')
        if await confirm_btn.count() > 0:
            await confirm_btn.click()
            await page.wait_for_url(index_url, timeout=30_000)
            return

        logger.warning("[%s] 未找到 2FA 元素，等待页面跳转", account.username)
        await page.wait_for_timeout(5_000)
    except PlaywrightTimeoutError as exc:
        logger.warning("[%s] 处理 2FA 超时: %s", account.username, exc)
    except PlaywrightError as exc:
        logger.warning("[%s] 处理 2FA 出错: %s", account.username, exc)


def _parse_profile(profile: dict[str, Any], account: Account) -> str:
    """Format the intercepted profile into a notification body (legacy parity)."""
    from mteam_cli.api import humanize as hz

    data: dict[str, Any] | None = profile.get("data") if profile else None
    if not data:
        return "获取到的数据为空"

    lines = [
        f"用户ID: {data.get('id')}",
        f"用户名: {data.get('username')}",
        f"用户Email: {data.get('email')}",
        f"登录IP: {data.get('ip')}",
        f"账户创建时间: {data.get('createdDate')}",
        f"账户更新时间: {data.get('lastModifiedDate')}",
    ]

    status = data.get("memberStatus")
    if status:
        lines += [
            f"会员最新登录时间: {status.get('lastLogin')}",
            f"会员最新浏览时间: {status.get('lastBrowse')}",
        ]

    count = data.get("memberCount")
    if count:
        lines += [
            f"上传量: {hz.naturalsize(count.get('uploaded'))}",
            f"下载量: {hz.naturalsize(count.get('downloaded'))}",
            f"魔力值: {hz.num(count.get('bonus'))}",
            f"分享率: {hz.ratio(count.get('shareRate'))}",
        ]

    return "\n".join(lines)
