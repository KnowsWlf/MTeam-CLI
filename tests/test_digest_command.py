"""命令层测试：digest 空结果文案（堵回归——曾对 seeders 类型谎报 IMDB）。"""

import asyncio
import textwrap
from types import SimpleNamespace

from mteam_cli.core.config import Settings
import mteam_cli.cli.commands.digest as digest_cmd


def _settings(tmp_path, toml_text):
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(toml_text), encoding="utf-8")
    return Settings.from_toml(p)


def _args(**over):
    base = dict(
        account=None, min_imdb=None, types=None, hours=None,
        limit=None, min_seeders=None, raw=False, output_format="table",
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_empty_message_mentions_seeders_for_music(tmp_path, monkeypatch):
    """music-only 查询无结果时，文案必须提做种门槛，不能只谎报 IMDB。"""
    settings = _settings(tmp_path, """
        [digest]
        types = ["music"]
        min_seeders = 30
        [[account]]
        username = "u1"
        api_key = "k1"
    """)

    async def fake_fetch(*a, **k):
        return []
    monkeypatch.setattr(digest_cmd, "fetch_high_score_digest", fake_fetch)

    captured = {}
    monkeypatch.setattr(digest_cmd, "notice", lambda msg: captured.setdefault("msg", msg))

    rc = asyncio.run(digest_cmd._run(_args(), settings))
    assert rc == 0
    assert "做种" in captured["msg"]      # 提到 seeders 信号
    assert "30" in captured["msg"]        # 实际生效的门槛
