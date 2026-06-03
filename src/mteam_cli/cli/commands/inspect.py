"""Dump login-page artifacts (HTML/PNG/JSON) for diagnosing DOM changes.

When M-Team changes its login DOM, the selectors in ``automation/login.py``
may break. Run ``mteam-cli inspect`` to capture the current login page so the
selectors can be updated against real markup.
"""

from __future__ import annotations

import argparse
import logging

from mteam_cli.cli._browser import browser_session_ctx
from mteam_cli.core.config import Settings


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("inspect", help="抓取登录页快照（DOM 变动排查用）。")
    p.add_argument(
        "--login",
        action="store_true",
        help="额外抓取 /login 页面（默认只抓首页）。",
    )
    p.set_defaults(func=handle)


async def handle(
    args: argparse.Namespace, settings: Settings, logger: logging.Logger
) -> int:
    async with browser_session_ctx(settings, logger) as ctx:
        await ctx.session.goto(f"{settings.base_url}/")
        bundle = await ctx.session.snapshot("inspect-home")
        print(f"首页快照: {bundle.html_path}")

        if args.login:
            await ctx.session.goto(f"{settings.base_url}/login")
            login_bundle = await ctx.session.snapshot("inspect-login")
            print(f"登录页快照: {login_bundle.html_path}")

    return 0
