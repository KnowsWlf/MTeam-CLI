"""Shared browser-session lifecycle for keep-alive commands.

Far simpler than the WeRead equivalent: no state-machine detection, no trace
plumbing. Just start a BrowserSession and guarantee close. Navigation + the
profile-XHR route are installed by ``automation.login.perform_login``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator

from mteam_cli.core.config import Settings

if TYPE_CHECKING:
    from mteam_cli.core.browser import BrowserSession


@dataclass(slots=True)
class BrowserAppContext:
    settings: Settings
    logger: logging.Logger
    session: "BrowserSession"


@asynccontextmanager
async def browser_session_ctx(
    settings: Settings,
    logger: logging.Logger,
    headless: bool | None = None,
) -> AsyncIterator[BrowserAppContext]:
    """Start a BrowserSession and always close it."""
    try:
        from mteam_cli.core.browser import BrowserSession
    except ModuleNotFoundError as exc:
        if exc.name == "playwright":
            print(
                "未安装 Playwright。请先执行 `pip install -e .` 与 "
                "`playwright install chromium`。"
            )
            raise SystemExit(1) from exc
        raise

    session = BrowserSession(settings, logger)
    await session.start(headless=headless)
    try:
        yield BrowserAppContext(settings=settings, logger=logger, session=session)
    finally:
        await session.close()
