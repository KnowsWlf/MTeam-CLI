"""Daily-trigger scheduler — one independent job per account.

Each account gets its own random
HH:MM inside the window, plus extra in-tick jitter so request bursts differ
even when two accounts land on the same minute. Exceptions inside a tick are
logged but never crash the loop; a heartbeat logs liveness for ``docker logs``.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Awaitable, Callable

import schedule

from mteam_cli.core.config import Account, Settings

# A factory that, given an account, returns an awaitable for one tick.
TickFactory = Callable[[Account], Awaitable[int]]


class DailyScheduler:
    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger,
        tick_factory: TickFactory,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.tick_factory = tick_factory
        self._pre_low, self._pre_high = _parse_range(
            settings.schedule_pre_delay_range, default=(10, 300)
        )

    def pick_daily_time(self) -> str:
        start_min, end_min = _parse_window(self.settings.schedule_window)
        # Support overnight / wrap-around windows (e.g. 23:00-06:00): when
        # start > end, pick across the wrap and fold back into 0–1439.
        span = end_min - start_min if end_min >= start_min else end_min + 1440 - start_min
        chosen = (start_min + random.randint(0, span)) % 1440
        return f"{chosen // 60:02d}:{chosen % 60:02d}"

    def loop(self) -> None:
        armed = 0
        for acct in self.settings.accounts:
            if not acct.can_keepalive:
                self.logger.info("跳过 %s（无保活凭证）", acct.username)
                continue
            run_time = self.pick_daily_time()
            schedule.every().day.at(run_time).do(self._make_job(acct))
            self.logger.info("已为 %s 安排每天 %s 保活", acct.username, run_time)
            armed += 1

        if armed == 0:
            self.logger.error("没有可保活账户，调度器空转。请配置 MTEAM_USERNAME/PASSWORD/TOTP_SECRET_<n>。")

        schedule.every(self.settings.schedule_heartbeat_hours).hours.do(self._heartbeat)
        self._heartbeat()

        try:
            while True:
                schedule.run_pending()
                time.sleep(60)
        except KeyboardInterrupt:
            self.logger.info("调度器被 SIGINT/SIGTERM 终止")

    def _make_job(self, account: Account) -> Callable[[], None]:
        def job() -> None:
            delay = random.randint(self._pre_low, self._pre_high)
            self.logger.info("[%s] 触发保活，先抖动 %ds…", account.username, delay)
            time.sleep(delay)
            try:
                exit_code = asyncio.run(self.tick_factory(account))
                self.logger.info("[%s] 保活完成: exit=%s", account.username, exit_code)
            except Exception:  # noqa: BLE001 — keep the loop alive
                self.logger.exception("[%s] 保活抛出异常；循环继续", account.username)

        return job

    def _heartbeat(self) -> None:
        next_runs = ", ".join(str(j.next_run) for j in schedule.jobs if j.next_run)
        self.logger.info("调度心跳：下次运行 %s", next_runs or "(无)")


def _parse_window(spec: str) -> tuple[int, int]:
    try:
        low, high = spec.split("-", 1)
        return _hhmm_to_min(low), _hhmm_to_min(high)
    except (ValueError, IndexError) as exc:
        raise ValueError(
            f"MTEAM_SCHEDULE_WINDOW 必须是 'HH:MM-HH:MM'（收到 {spec!r}）"
        ) from exc


def _hhmm_to_min(hhmm: str) -> int:
    h, m = hhmm.strip().split(":", 1)
    h_int, m_int = int(h), int(m)
    if not (0 <= h_int <= 23 and 0 <= m_int <= 59):
        raise ValueError(f"非法时间 {hhmm!r}")
    return h_int * 60 + m_int


def _parse_range(spec: str, default: tuple[int, int]) -> tuple[int, int]:
    try:
        a, b = spec.split("-", 1)
        low, high = int(a), int(b)
        if low < 0 or high < low:
            return default
        return low, high
    except (ValueError, IndexError):
        return default
