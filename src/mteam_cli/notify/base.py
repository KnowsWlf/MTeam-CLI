"""Notifier abstraction: Protocol + Notification payload + concurrent Hub."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class NotificationEvent(str, Enum):
    CHECKIN_DONE = "checkin_done"      # keep-alive login succeeded
    CHECKIN_FAILED = "checkin_failed"  # keep-alive login failed


@dataclass(slots=True)
class Notification:
    event: NotificationEvent
    title: str
    body: str


class Notifier(Protocol):
    name: str

    async def send(self, n: Notification) -> None:
        ...


class NotifierHub:
    """Fan-out to all registered notifiers concurrently; errors are isolated."""

    def __init__(self, notifiers: list[Notifier], logger: logging.Logger) -> None:
        self._notifiers = notifiers
        self._logger = logger

    @property
    def enabled_names(self) -> list[str]:
        return [n.name for n in self._notifiers]

    async def notify(self, n: Notification) -> None:
        if not self._notifiers:
            self._logger.debug("No notifiers enabled; skipping %s", n.event.value)
            return
        results = await asyncio.gather(
            *(self._safe_send(notifier, n) for notifier in self._notifiers),
            return_exceptions=False,
        )
        ok = sum(1 for r in results if r)
        self._logger.info(
            "Notify %s → %d/%d delivered (%s)",
            n.event.value,
            ok,
            len(self._notifiers),
            ", ".join(self.enabled_names),
        )

    async def _safe_send(self, notifier: Notifier, n: Notification) -> bool:
        try:
            await notifier.send(n)
            return True
        except Exception as exc:
            self._logger.warning(
                "Notifier %s failed for %s: %s", notifier.name, n.event.value, exc
            )
            return False
