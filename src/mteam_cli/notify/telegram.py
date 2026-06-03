"""Telegram Bot API notifier — text only, pure urllib."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mteam_cli.notify.base import Notification

_TG_API = "https://api.telegram.org"

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TelegramNotifier:
    token: str
    chat_id: str
    name: str = "telegram"
    timeout_seconds: int = 15

    async def send(self, n: Notification) -> None:
        # Plain text (no parse_mode): the body is a profile dump / error string
        # that routinely contains Markdown metachars (e.g. '_' in usernames or
        # 'qBittorrent/5.2.0'); parsing as Markdown would 400 and silently drop
        # the alert.
        text = f"{n.title}\n\n{n.body}"
        await asyncio.to_thread(self._send_message, text)

    def _send_message(self, text: str) -> None:
        url = f"{_TG_API}/bot{self.token}/sendMessage"
        data = urlencode(
            {"chat_id": self.chat_id, "text": text}
        ).encode("utf-8")
        req = Request(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urlopen(req, timeout=self.timeout_seconds) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                if not payload.get("ok"):
                    raise RuntimeError(
                        f"Telegram API error: {payload.get('description')!r}"
                    )
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Telegram HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Telegram network error: {exc.reason}") from exc
