"""Pluggable notification system for M-Team keep-alive.

Two events: CHECKIN_DONE / CHECKIN_FAILED. Notifiers are built PER-ACCOUNT by
``factory.build_notifier_hub(account, logger)`` from that account's own notify
vars; absent config → channel disabled silently. There is no global notifier.
"""

from mteam_cli.notify.base import (
    Notification,
    NotificationEvent,
    Notifier,
    NotifierHub,
)
from mteam_cli.notify.factory import build_notifier_hub

__all__ = [
    "Notification",
    "NotificationEvent",
    "Notifier",
    "NotifierHub",
    "build_notifier_hub",
]
