from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]


def _coalesce(value, default):
    """返回 value，除非它是 None（此时返回 default）。

    不能用 ``value or default``：``0.0`` / ``0`` 是合法配置值，
    ``or`` 会把它们当假值吞掉。
    """
    return value if value is not None else default


def _resolve_config_path(path: Path | None) -> Path:
    """三级发现：显式 path > ``MTEAM_CONFIG`` env > 默认 ``ROOT_DIR/config.toml``。"""
    if path is not None:
        return path
    env = os.getenv("MTEAM_CONFIG")
    if env and env.strip():
        return Path(env.strip())
    return ROOT_DIR / "config.toml"


def _load_toml(path: Path) -> dict:
    """读并解析 TOML；文件不存在 → 清晰 SystemExit 指向 template。"""
    if not path.exists():
        raise SystemExit(
            f"配置文件不存在：{path}\n"
            f"请复制 config.toml.template 为 config.toml 并填写（或用 --config/MTEAM_CONFIG 指定路径）。"
        )
    with path.open("rb") as f:
        return tomllib.load(f)


def _env_secret(name: str) -> str | None:
    """读密钥 env 覆盖；空/未设 → None（「空即不设」：空串不算覆盖）。"""
    raw = os.getenv(name)
    return raw.strip() if raw and raw.strip() else None


@dataclass(slots=True, frozen=True)
class DigestConfig:
    """一个账户解析后的最终 digest 参数（全局默认 + 账户覆盖合并后）。"""

    types: list[str]
    min_imdb: float
    hours: int
    limit: int
    min_seeders: int  # 非 imdb 类型（music/adult…）的做种数门槛


@dataclass(slots=True, frozen=True)
class Account:
    """One M-Team account.

    Credentials are independent: ``username``/``password``/``totp_secret`` →
    browser keep-alive; ``api_key`` → data queries.  Per-account notify config
    (Telegram / Feishu / SMTP-to) is per-account; the SMTP *server* is shared
    (see ``Settings``).

    ``has_smtp`` needs both the global SMTP server AND a per-account recipient.
    """

    username: str
    password: str | None = None
    totp_secret: str | None = None
    api_key: str | None = None
    # ── per-account notify ──
    telegram_token: str | None = None
    telegram_chat_id: str | None = None
    feishu_token: str | None = None
    smtp_to: str | None = None  # recipient(s); server config lives on Settings
    digest_enabled: bool = False
    # ── per-account digest overrides (None = 继承全局 Settings.digest_*) ──
    digest_types: list[str] | None = None
    digest_min_imdb: float | None = None
    digest_hours: int | None = None
    digest_limit: int | None = None
    digest_min_seeders: int | None = None

    @property
    def safe_name(self) -> str:
        return re.sub(r"[^\w\-]", "_", self.username)

    def storage_path(self, auth_dir: Path) -> Path:
        return auth_dir / f"mteam_{self.safe_name}.json"

    @property
    def can_keepalive(self) -> bool:
        return bool(self.username and self.password and self.totp_secret)

    @property
    def can_query(self) -> bool:
        return bool(self.api_key)

    def ensure_keepalive(self) -> None:
        """Guard: raise ``SystemExit`` if this account can't keep-alive."""
        if not self.can_keepalive:
            raise SystemExit(
                f"账户 {self.username!r} 缺少保活所需凭证"
                f"（需要 MTEAM_USERNAME/PASSWORD/TOTP_SECRET_<n>）。"
            )

    def ensure_query(self) -> None:
        """Guard: raise ``SystemExit`` if this account has no API key."""
        if not self.can_query:
            raise SystemExit(
                f"账户 {self.username!r} 未配置 API key。"
                f"请在 .env 设置对应的 MTEAM_API_KEY_<n>（在 M-Team 控制台生成）。"
            )

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)

    @property
    def has_feishu(self) -> bool:
        return bool(self.feishu_token)

    def has_smtp(self, settings: "Settings") -> bool:
        return bool(settings.smtp_host and settings.smtp_from and self.smtp_to)

    def resolved_digest_config(self, settings: "Settings") -> "DigestConfig":
        """合并全局默认 + 本账户覆盖，得到最终 digest 参数（合并规则唯一来源）。

        `types` 用 ``or``（空列表继承全局正是期望）；数值维度用
        ``_coalesce``，否则 ``min_imdb=0.0`` / ``limit=0`` 会被当假值吞掉。
        """
        return DigestConfig(
            types=self.digest_types or settings.digest_types,
            min_imdb=_coalesce(self.digest_min_imdb, settings.digest_min_imdb),
            hours=_coalesce(self.digest_hours, settings.digest_hours),
            limit=_coalesce(self.digest_limit, settings.digest_limit),
            min_seeders=_coalesce(self.digest_min_seeders, settings.digest_min_seeders),
        )


@dataclass(slots=True)
class Settings:
    base_url: str
    api_base_url: str
    headless: bool
    slow_mo_ms: int
    timeout_ms: int
    auth_dir: Path
    log_dir: Path
    artifact_dir: Path
    accounts: list[Account] = field(default_factory=list)
    # ── SMTP server (global, shared across accounts; recipient is per-account) ──
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    # ── digest（高分新片摘要，全局参数）──
    digest_min_imdb: float = 8.0
    digest_types: list[str] = field(default_factory=lambda: ["movie", "tvshow"])
    digest_hours: int = 24
    digest_limit: int = 10
    digest_min_seeders: int = 30  # 非 imdb 类型的做种数门槛（全局默认）
    # ── schedule (global infra knobs) ──
    schedule_window: str = "09:00-11:00"
    schedule_pre_delay_range: str = "10-300"
    schedule_heartbeat_hours: int = 1

    @classmethod
    def from_toml(cls, path: Path | None = None) -> "Settings":
        """从 TOML 文件构造 Settings（密钥可被 env 覆盖，见 _parse_accounts_toml）。

        文件发现三级：显式 path > MTEAM_CONFIG env > ROOT_DIR/config.toml。
        """
        data = _load_toml(_resolve_config_path(path))
        site = data.get("site", {})
        schedule = data.get("schedule", {})
        smtp = data.get("smtp", {})
        digest = data.get("digest", {})

        base_url = str(site.get("base_url", "https://zp.m-team.io")).strip().rstrip("/")
        api_base_url = str(
            site.get("api_base_url", "https://api.m-team.cc/api")
        ).strip().rstrip("/")

        return cls(
            base_url=base_url,
            api_base_url=api_base_url,
            headless=bool(site.get("headless", True)),
            slow_mo_ms=int(site.get("slow_mo_ms", 0)),
            timeout_ms=int(site.get("timeout_ms", 60_000)),
            auth_dir=ROOT_DIR / str(site.get("auth_dir", "data/auth")),
            log_dir=ROOT_DIR / str(site.get("log_dir", "data/logs")),
            artifact_dir=ROOT_DIR / str(site.get("artifact_dir", "data/artifacts")),
            accounts=cls._parse_accounts_toml(data.get("account", [])),
            smtp_host=str(smtp.get("host", "")).strip(),
            smtp_port=int(smtp.get("port", 465)),
            smtp_user=str(smtp.get("user", "")).strip(),
            smtp_password=_env_secret("NOTIFY_SMTP_PASSWORD") or str(smtp.get("password", "")),
            smtp_from=str(smtp.get("from", "")).strip(),
            smtp_use_tls=bool(smtp.get("use_tls", True)),
            digest_min_imdb=float(digest.get("min_imdb", 8.0)),
            digest_types=list(digest.get("types", ["movie", "tvshow"])),
            digest_hours=int(digest.get("hours", 24)),
            digest_limit=int(digest.get("limit", 10)),
            digest_min_seeders=int(digest.get("min_seeders", 30)),
            schedule_window=str(schedule.get("window", "09:00-11:00")).strip(),
            schedule_pre_delay_range=str(schedule.get("pre_delay_range", "10-300")).strip(),
            schedule_heartbeat_hours=int(schedule.get("heartbeat_hours", 1)),
        )

    @staticmethod
    def _parse_accounts_toml(items: list[dict]) -> list[Account]:
        """把 TOML 的 [[account]] 数组解析为 Account 列表。

        密钥（password/totp_secret/api_key）可被 env 覆盖：``MTEAM_PASSWORD_i`` 等，
        ``i`` = 数组中的 1-based 序号。env 优先于 TOML 值；env 空/未设则用 TOML。
        """
        accounts: list[Account] = []
        for i, a in enumerate(items, start=1):
            notify = a.get("notify", {})
            adigest = a.get("digest", {})
            accounts.append(
                Account(
                    username=a["username"],
                    password=_env_secret(f"MTEAM_PASSWORD_{i}") or (a.get("password") or None),
                    totp_secret=_env_secret(f"MTEAM_TOTP_SECRET_{i}") or (a.get("totp_secret") or None),
                    api_key=_env_secret(f"MTEAM_API_KEY_{i}") or (a.get("api_key") or None),
                    telegram_token=notify.get("telegram_token") or None,
                    telegram_chat_id=notify.get("telegram_chat_id") or None,
                    feishu_token=notify.get("feishu_token") or None,
                    smtp_to=notify.get("smtp_to") or None,
                    digest_enabled=bool(a.get("digest_enabled", False)),
                    # 原生类型，无需 split / 转换；缺键 → None（继承全局，合并在 resolved_digest_config）
                    digest_types=adigest.get("types"),
                    digest_min_imdb=adigest.get("min_imdb"),
                    digest_hours=adigest.get("hours"),
                    digest_limit=adigest.get("limit"),
                    digest_min_seeders=adigest.get("min_seeders"),
                )
            )
        return accounts

    def resolve_account(self, name: str | None) -> Account:
        if not self.accounts:
            raise SystemExit(
                "未配置任何账户。请在 config.toml 添加至少一个 [[account]]（见 config.toml.template）。"
            )
        if name is None:
            return self.accounts[0]
        for acct in self.accounts:
            if acct.username == name:
                return acct
        names = ", ".join(a.username for a in self.accounts) or "(无)"
        raise SystemExit(f"未知账户 {name!r}。已配置账户：{names}")

    def ensure_directories(self) -> None:
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
