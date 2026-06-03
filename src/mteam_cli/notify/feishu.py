"""Feishu (Lark) bot webhook notifier — text only, pure urllib.

Posts to the Feishu bot v2 webhook with the configured token:
webhook with the configured token.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mteam_cli.notify.base import Notification

_FEISHU_HOOK = "https://open.feishu.cn/open-apis/bot/v2/hook"

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FeishuNotifier:
    token: str
    name: str = "feishu"
    timeout_seconds: int = 15

    async def send(self, n: Notification) -> None:
        text = f"{n.title}\n\n{n.body}"
        await asyncio.to_thread(self._send, text)

    def _send(self, text: str) -> None:
        url = f"{_FEISHU_HOOK}/{self.token}"
        data = json.dumps(
            {"msg_type": "text", "content": {"text": text}}
        ).encode("utf-8")
        req = Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urlopen(req, timeout=self.timeout_seconds) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                # Feishu returns {"code":0,...} on success (StatusCode legacy = 0).
                code = payload.get("code", payload.get("StatusCode"))
                if code not in (0, None):
                    raise RuntimeError(f"Feishu API error: {payload}")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Feishu HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Feishu network error: {exc.reason}") from exc
