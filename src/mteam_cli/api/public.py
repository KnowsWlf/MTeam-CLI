"""Thin wrappers over M-Team API endpoints (verified against the OpenAPI spec).

Every endpoint is POST. Some take query params (``uid``/``id``), others a JSON
body. Each function takes ``api_key`` + ``base_url`` and returns the raw ``data``
payload; field shaping into rows happens in the command layer.

Pagination: production (``api.m-team.cc``) uses ``pageNumber``/``pageSize`` —
verified against the working mcp-server-mteam reference. (The OpenAPI test
server documented ``page``; production rejects it. Keep that delta noted here,
in the one place it's encoded.)
"""

from __future__ import annotations

from typing import Any

from mteam_cli.api._internal import MTeamAPIError, api_post


async def get_profile(api_key: str, *, base_url: str, uid: int | str | None = None) -> Any:
    """Member profile + counters. ``uid`` omitted → the API key's own profile."""
    return await api_post(
        "/member/profile", api_key=api_key, base_url=base_url, params={"uid": uid}
    )


async def get_own_uid(api_key: str, *, base_url: str) -> Any:
    """Resolve the API key owner's own uid via the self profile (data.id)."""
    data = await get_profile(api_key, base_url=base_url)
    if isinstance(data, dict):
        return data.get("id")
    raise MTeamAPIError("无法从 profile 解析自身 uid")


async def search_torrents(
    api_key: str,
    keyword: str,
    *,
    base_url: str,
    mode: str = "normal",
    page_number: int = 1,
    page_size: int = 20,
) -> Any:
    """Search torrents. JSON body ``{keyword, mode, pageNumber, pageSize}``.

    ``mode``: normal/adult/movie/music/tvshow/waterfall/rss/rankings/all.
    Verified against the working mcp-server-mteam reference (production uses
    ``pageNumber``, not the test server's ``page``).
    """
    body: dict[str, Any] = {
        "keyword": keyword,
        "mode": mode,
        "pageNumber": page_number,
        "pageSize": page_size,
    }
    return await api_post("/torrent/search", api_key=api_key, base_url=base_url, body=body)


async def get_torrent_detail(api_key: str, torrent_id: str, *, base_url: str) -> Any:
    """Full detail for one torrent id (form-encoded ``id``, per reference)."""
    return await api_post(
        "/torrent/detail", api_key=api_key, base_url=base_url, form={"id": torrent_id}
    )


async def gen_dl_token(api_key: str, torrent_id: str, *, base_url: str) -> Any:
    """Generate a download URL for a torrent id (form-encoded ``id``); data is a URL string."""
    return await api_post(
        "/torrent/genDlToken", api_key=api_key, base_url=base_url, form={"id": torrent_id}
    )


async def get_peer_list(
    api_key: str,
    uid: int | str,
    *,
    base_url: str,
    leeching: bool = False,
    page_number: int = 1,
    page_size: int = 50,
) -> Any:
    """Current seeding (default) or leeching torrents (body UserTorrentSearch).

    Production uses ``pageNumber`` (like /torrent/search), not the test
    server's ``page``.
    """
    # Captured from the web UI: the field is "userid" (not "uid"), with
    # pageNumber/pageSize. The web's _timestamp/_sgin signature is browser-only
    # anti-replay; API-key clients don't send it.
    body = {
        "userid": str(uid),
        "type": "LEECHING" if leeching else "SEEDING",
        "pageNumber": page_number,
        "pageSize": page_size,
    }
    return await api_post(
        "/member/getUserTorrentList", api_key=api_key, base_url=base_url, body=body
    )


async def get_hnr(
    uid: int | str,
    *,
    base_url: str,
    auth_token: str,
    did: str | None = None,
    visitorid: str | None = None,
) -> Any:
    """Hit-and-run / crime records (query ``uid``). Requires the web session JWT
    (the API key is rejected with 無許可權)."""
    return await api_post(
        "/member/getCrimeRecords",
        base_url=base_url,
        auth_token=auth_token,
        did=did,
        visitorid=visitorid,
        params={"uid": uid},
    )


async def get_messages(
    *,
    base_url: str,
    auth_token: str,
    did: str | None = None,
    visitorid: str | None = None,
    box_id: int | None = None,
    keyword: str = "",
    page_number: int = 1,
    page_size: int = 20,
) -> Any:
    """Inbox / private messages (body MessageSearch). Requires the web session
    JWT (the API key returns 401 Full authentication required)."""
    body: dict[str, Any] = {"pageNumber": page_number, "pageSize": page_size}
    if box_id is not None:
        body["boxId"] = box_id
    if keyword:
        body["keyword"] = keyword
    return await api_post(
        "/msg/search",
        base_url=base_url,
        auth_token=auth_token,
        did=did,
        visitorid=visitorid,
        body=body,
    )


async def get_notices(api_key: str, *, base_url: str) -> Any:
    """Site announcements / news (no params)."""
    return await api_post("/system/news", api_key=api_key, base_url=base_url)


# ── shape helper (tolerant to paginated vs flat shapes) ────────


def as_list(data: Any) -> list[dict[str, Any]]:
    """Extract a list of records from an envelope of unknown exact shape.

    M-Team paginated endpoints typically return ``{"data": [...]}`` or
    ``{"data": [...], "total": N}`` nested under ``data``. Be liberal so a minor
    shape change doesn't break the command.
    """
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("data", "list", "records", "rows", "result"):
            inner = data.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
            if isinstance(inner, dict):
                nested = as_list(inner)
                if nested:
                    return nested
    return []
