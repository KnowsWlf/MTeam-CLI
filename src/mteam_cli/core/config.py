from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]

try:
    from dotenv import load_dotenv

    env_path = ROOT_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:  # pragma: no cover
    pass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw.strip())


def _suffixed(name: str, i: int) -> str | None:
    raw = os.getenv(f"{name}_{i}")
    return raw.strip() if raw and raw.strip() else None


def _suffixed_int(name: str, i: int) -> int | None:
    raw = os.getenv(f"{name}_{i}")
    if raw is None or not raw.strip():
        return None
    return int(raw.strip())


def _suffixed_float(name: str, i: int) -> float | None:
    raw = os.getenv(f"{name}_{i}")
    if raw is None or not raw.strip():
        return None
    return float(raw.strip())


def _coalesce(value, default):
    """返回 value，除非它是 None（此时返回 default）。

    不能用 ``value or default``：``0.0`` / ``0`` 是合法配置值，
    ``or`` 会把它们当假值吞掉。
    """
    return value if value is not None else default


@dataclass(slots=True, frozen=True)
class DigestConfig:
    """一个账户解析后的最终 digest 参数（全局默认 + 账户覆盖合并后）。"""

    types: list[str]
    min_imdb: float
    hours: int
    limit: int


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
    # ── schedule (global infra knobs) ──
    schedule_window: str = "09:00-11:00"
    schedule_pre_delay_range: str = "10-300"
    schedule_heartbeat_hours: int = 1

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            base_url=os.getenv("MTEAM_BASE_URL", "https://zp.m-team.io").strip().rstrip("/"),
            api_base_url=os.getenv("MTEAM_API_BASE_URL", "https://api.m-team.cc/api").strip().rstrip("/"),
            headless=_env_bool("MTEAM_HEADLESS", True),
            slow_mo_ms=_env_int("MTEAM_SLOW_MO_MS", 0),
            timeout_ms=_env_int("MTEAM_TIMEOUT_MS", 60_000),
            auth_dir=ROOT_DIR / os.getenv("MTEAM_AUTH_DIR", "data/auth"),
            log_dir=ROOT_DIR / os.getenv("MTEAM_LOG_DIR", "data/logs"),
            artifact_dir=ROOT_DIR / os.getenv("MTEAM_ARTIFACT_DIR", "data/artifacts"),
            accounts=cls._parse_accounts(),
            smtp_host=os.getenv("NOTIFY_SMTP_HOST", "").strip(),
            smtp_port=_env_int("NOTIFY_SMTP_PORT", 465),
            smtp_user=os.getenv("NOTIFY_SMTP_USER", "").strip(),
            smtp_password=os.getenv("NOTIFY_SMTP_PASSWORD", ""),
            smtp_from=os.getenv("NOTIFY_SMTP_FROM", "").strip(),
            smtp_use_tls=_env_bool("NOTIFY_SMTP_USE_TLS", True),
            digest_min_imdb=float(os.getenv("MTEAM_DIGEST_MIN_IMDB", "8.0")),
            digest_types=[
                t.strip()
                for t in os.getenv("MTEAM_DIGEST_TYPES", "movie,tvshow").split(",")
                if t.strip()
            ],
            digest_hours=_env_int("MTEAM_DIGEST_HOURS", 24),
            digest_limit=_env_int("MTEAM_DIGEST_LIMIT", 10),
            schedule_window=os.getenv("MTEAM_SCHEDULE_WINDOW", "09:00-11:00").strip(),
            schedule_pre_delay_range=os.getenv("MTEAM_SCHEDULE_PRE_DELAY_RANGE", "10-300").strip(),
            schedule_heartbeat_hours=_env_int("MTEAM_SCHEDULE_HEARTBEAT_HOURS", 1),
        )

    @staticmethod
    def _parse_accounts() -> list[Account]:
        accounts: list[Account] = []
        i = 1
        while True:
            username = _suffixed("MTEAM_USERNAME", i)
            api_key = _suffixed("MTEAM_API_KEY", i)
            if not username and not api_key:
                break
            if not username:
                i += 1
                continue

            smtp_to = _suffixed("NOTIFY_SMTP_TO", i) or _suffixed("NOTIFY_EMAIL", i)
            accounts.append(
                Account(
                    username=username,
                    password=(os.getenv(f"MTEAM_PASSWORD_{i}") or "") or None,
                    totp_secret=_suffixed("MTEAM_TOTP_SECRET", i),
                    api_key=api_key,
                    telegram_token=_suffixed("NOTIFY_TELEGRAM_TOKEN", i),
                    telegram_chat_id=_suffixed("NOTIFY_TELEGRAM_CHAT_ID", i),
                    feishu_token=_suffixed("NOTIFY_FEISHU_TOKEN", i),
                    smtp_to=smtp_to,
                    digest_enabled=_env_bool(f"MTEAM_DIGEST_ENABLED_{i}", False),
                    digest_types=(
                        [t.strip() for t in raw.split(",") if t.strip()]
                        if (raw := _suffixed("MTEAM_DIGEST_TYPES", i))
                        else None
                    ),
                    digest_min_imdb=_suffixed_float("MTEAM_DIGEST_MIN_IMDB", i),
                    digest_hours=_suffixed_int("MTEAM_DIGEST_HOURS", i),
                    digest_limit=_suffixed_int("MTEAM_DIGEST_LIMIT", i),
                )
            )
            i += 1
        return accounts

    def resolve_account(self, name: str | None) -> Account:
        if not self.accounts:
            raise SystemExit(
                "未配置任何账户。请设置 MTEAM_USERNAME_1 / MTEAM_API_KEY_1 等环境变量。"
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
