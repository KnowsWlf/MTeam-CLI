"""Load a logged-in web session (JWT) from a per-account localStorage snapshot.

Some M-Team endpoints (messages, crime/H&R records) reject the API key with
"Full authentication is required" / "無許可權" — they need the browser session's
JWT, the same one the SPA sends as the ``authorization`` header. The keep-alive
``login``/``run`` flow already persists that token in the localStorage snapshot
under the ``auth`` key, so data commands can reuse it without a browser.

Pure file I/O + base64 — no Playwright import (keeps the data layer light).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class WebSession:
    auth_token: str
    did: str | None = None
    visitorid: str | None = None
    uid: int | None = None


def load_session(storage_path: Path) -> WebSession | None:
    """Return the web session from a localStorage snapshot, or ``None``.

    ``None`` means no usable session — the caller should tell the user to run
    ``mteam-cli login`` first.
    """
    if not storage_path.exists():
        return None
    try:
        data = json.loads(storage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    token = data.get("auth")
    if not isinstance(token, str) or token.count(".") != 2:
        return None

    return WebSession(
        auth_token=token,
        did=data.get("did"),
        visitorid=data.get("visitorId"),
        uid=_uid_from_jwt(token),
    )


def _uid_from_jwt(token: str) -> int | None:
    """Decode the JWT payload (no verification) to read the ``uid`` claim."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        uid = payload.get("uid")
        return int(uid) if uid is not None else None
    except (ValueError, IndexError, json.JSONDecodeError, UnicodeDecodeError):
        return None
