"""M-Team data API (pure HTTP, x-api-key auth — no Playwright).

Re-export the public surface so commands can do
``from mteam_cli.api import get_profile``.
"""

from mteam_cli.api._internal import (
    MTeamAPIError,
    MTeamAuthError,
    api_post,
)
from mteam_cli.api.public import (
    gen_dl_token,
    get_hnr,
    get_messages,
    get_notices,
    get_own_uid,
    get_peer_list,
    get_profile,
    get_torrent_detail,
    search_torrents,
)
from mteam_cli.api.session import WebSession, load_session
from mteam_cli.api.digest import fetch_high_score_digest, format_digest

__all__ = [
    "MTeamAPIError",
    "MTeamAuthError",
    "api_post",
    "get_profile",
    "get_own_uid",
    "search_torrents",
    "get_torrent_detail",
    "gen_dl_token",
    "get_peer_list",
    "get_hnr",
    "get_messages",
    "get_notices",
    "WebSession",
    "load_session",
    "fetch_high_score_digest",
    "format_digest",
]
