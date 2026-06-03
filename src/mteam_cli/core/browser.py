"""Minimal Playwright browser lifecycle for the keep-alive login flow.

Trimmed from the WeRead BrowserSession: no state-machine detection and no
storage_state injection — M-Team stores its auth token in localStorage, which
is loaded/saved explicitly by ``automation.localstorage.LocalStorageManager``
(the approach proven in the legacy script).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from mteam_cli.core.config import Settings
from mteam_cli.core.models import SnapshotBundle


class BrowserSession:
    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self.settings = settings
        self.logger = logger
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def start(self, headless: bool | None = None) -> "BrowserSession":
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.settings.headless if headless is None else headless,
            slow_mo=self.settings.slow_mo_ms,
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1440, "height": 960},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.settings.timeout_ms)
        return self

    async def goto(self, url: str) -> None:
        if self.page is None:
            raise RuntimeError("Browser session has not been started.")
        self.logger.info("Navigating to %s", url)
        await self.page.goto(url, timeout=self.settings.timeout_ms)
        await self.wait_until_settled()

    async def wait_until_settled(self) -> None:
        if self.page is None:
            raise RuntimeError("Browser session has not been started.")
        try:
            await self.page.wait_for_load_state("networkidle", timeout=self.settings.timeout_ms)
        except PlaywrightTimeoutError:
            pass

    async def snapshot(self, prefix: str, metadata: dict[str, object] | None = None) -> SnapshotBundle:
        if self.page is None:
            raise RuntimeError("Browser session has not been started.")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        stem = f"{prefix}-{timestamp}"
        png_path = self.settings.artifact_dir / f"{stem}.png"
        html_path = self.settings.artifact_dir / f"{stem}.html"
        metadata_path = self.settings.artifact_dir / f"{stem}.json"

        self.settings.artifact_dir.mkdir(parents=True, exist_ok=True)
        await self.wait_until_settled()
        await self.page.screenshot(path=str(png_path), full_page=True)
        html_path.write_text(await self.page.content(), encoding="utf-8")
        payload = {
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "url": self.page.url,
            "title": await self.page.title(),
            "metadata": metadata or {},
        }
        metadata_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.logger.info("Saved snapshot artifacts under %s", self.settings.artifact_dir)
        return SnapshotBundle(
            screenshot_path=png_path,
            html_path=html_path,
            metadata_path=metadata_path,
        )

    async def close(self) -> None:
        if self.context is not None:
            await self.context.close()
        if self.browser is not None:
            await self.browser.close()
        if self.playwright is not None:
            await self.playwright.stop()
