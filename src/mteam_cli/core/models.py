from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ActionResult:
    """Generic outcome of a browser action."""

    success: bool
    message: str


@dataclass(slots=True)
class CheckinResult:
    """Outcome of one account's keep-alive login tick."""

    username: str
    ok: bool
    skipped: bool = False
    profile_text: str = ""
    error: str = ""


@dataclass(slots=True)
class SnapshotBundle:
    screenshot_path: Path
    html_path: Path
    metadata_path: Path
