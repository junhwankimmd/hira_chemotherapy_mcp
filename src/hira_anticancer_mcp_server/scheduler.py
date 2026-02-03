"""
스케줄러 모듈 — 매일 1회 자동 업데이트 확인 + Telegram 알림.

APScheduler의 AsyncIOScheduler를 사용하여 매일 지정 시각에 check_for_updates를 실행합니다.
on/off 제어가 가능하며, 상태는 config.json에 영속화됩니다.

사용 예:
  scheduler = HiraScheduler(data_dir=Path("~/.hira-anticancer-data"))
  await scheduler.start()
  scheduler.pause()
  scheduler.resume()
  await scheduler.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
DEFAULT_CHECK_HOUR = 9   # 매일 오전 9시 (KST)
DEFAULT_CHECK_MINUTE = 0
JOB_ID = "hira_daily_check"


class HiraScheduler:
    """
    매일 1회 HIRA 파일 변경을 확인하고 Telegram으로 알림하는 스케줄러.

    내부적으로 asyncio.Task 기반으로 구현하여 외부 의존성을 최소화합니다.
    APScheduler 설치 없이도 작동합니다.
    """

    def __init__(
        self,
        data_dir: Path,
        *,
        check_hour: int = DEFAULT_CHECK_HOUR,
        check_minute: int = DEFAULT_CHECK_MINUTE,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.check_hour = check_hour
        self.check_minute = check_minute
        self.config_path = self.data_dir / "scheduler_config.json"

        self._task: asyncio.Task | None = None
        self._enabled: bool = True
        self._running: bool = False
        self._last_result: dict | None = None
        self._last_run: str | None = None

        self._load_config()

    # ── Config persistence ───────────────────────────────────────────

    def _load_config(self) -> None:
        """저장된 설정이 있으면 로드합니다."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self._enabled = cfg.get("enabled", True)
                self.check_hour = cfg.get("check_hour", DEFAULT_CHECK_HOUR)
                self.check_minute = cfg.get("check_minute", DEFAULT_CHECK_MINUTE)
                self._last_run = cfg.get("last_run")
                logger.info(f"스케줄러 설정 로드: enabled={self._enabled}, "
                           f"시각={self.check_hour:02d}:{self.check_minute:02d}")
            except Exception as e:
                logger.warning(f"설정 로드 실패: {e}")

    def _save_config(self) -> None:
        """현재 설정을 저장합니다."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        cfg = {
            "enabled": self._enabled,
            "check_hour": self.check_hour,
            "check_minute": self.check_minute,
            "last_run": self._last_run,
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

    # ── Core scheduling loop ─────────────────────────────────────────

    def _seconds_until_next_run(self) -> float:
        """다음 실행까지 남은 초를 계산합니다."""
        now = datetime.now(KST)
        target = now.replace(
            hour=self.check_hour,
            minute=self.check_minute,
            second=0,
            microsecond=0,
        )
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    async def _run_check(self) -> dict:
        """업데이트 확인 + Telegram 알림을 실행합니다."""
        from .scraper import check_for_updates
        from .notifier import notify_updates

        logger.info("스케줄된 업데이트 확인 시작…")
        try:
            results = await check_for_updates(self.data_dir)
            self._last_result = results
            self._last_run = results.get("checked_at", "?")
            self._save_config()

            # Telegram 알림 (변경 있을 때만)
            await notify_updates(results, force=False)

            return results
        except Exception as exc:
            logger.error(f"스케줄 실행 오류: {exc}")
            # 에러도 Telegram으로 알림
            from .notifier import send_telegram
            await send_telegram(
                f"⚠️ <b>HIRA 모니터링 오류</b>\n\n{exc}",
            )
            return {"error": str(exc)}

    async def _loop(self) -> None:
        """메인 스케줄링 루프 — 매일 지정 시각에 실행합니다."""
        self._running = True
        logger.info(
            f"스케줄러 루프 시작 — 매일 {self.check_hour:02d}:{self.check_minute:02d} KST"
        )

        while self._running:
            wait = self._seconds_until_next_run()
            logger.info(f"다음 실행까지 {wait/3600:.1f}시간 대기")

            try:
                await asyncio.sleep(wait)
            except asyncio.CancelledError:
                logger.info("스케줄러 루프 취소됨")
                break

            if self._enabled and self._running:
                await self._run_check()
            elif not self._enabled:
                logger.info("스케줄러 비활성 상태 — 실행 건너뜀")

    # ── Public API ───────────────────────────────────────────────────

    async def start(self) -> None:
        """스케줄러를 시작합니다."""
        if self._task is not None and not self._task.done():
            logger.warning("스케줄러가 이미 실행 중입니다")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("스케줄러 시작됨")

    async def stop(self) -> None:
        """스케줄러를 중지합니다."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("스케줄러 중지됨")

    def enable(self) -> dict:
        """스케줄러를 활성화합니다 (on)."""
        self._enabled = True
        self._save_config()
        logger.info("스케줄러 활성화됨 (ON)")
        return self.get_status()

    def disable(self) -> dict:
        """스케줄러를 비활성화합니다 (off)."""
        self._enabled = False
        self._save_config()
        logger.info("스케줄러 비활성화됨 (OFF)")
        return self.get_status()

    def set_schedule(self, hour: int, minute: int = 0) -> dict:
        """체크 시각을 변경합니다."""
        self.check_hour = hour
        self.check_minute = minute
        self._save_config()
        logger.info(f"체크 시각 변경: {hour:02d}:{minute:02d} KST")
        return self.get_status()

    def get_status(self) -> dict:
        """스케줄러 상태를 반환합니다."""
        wait = self._seconds_until_next_run() if self._running else None
        return {
            "enabled": self._enabled,
            "running": self._running,
            "schedule": f"{self.check_hour:02d}:{self.check_minute:02d} KST (매일)",
            "next_run_in": f"{wait/3600:.1f}시간" if wait else "중지됨",
            "last_run": self._last_run,
            "last_result_summary": self._summarize_last(),
        }

    def _summarize_last(self) -> str | None:
        """마지막 결과를 요약합니다."""
        if not self._last_result:
            return None
        files = self._last_result.get("files", {})
        updates = [k for k, v in files.items() if v.get("has_update")]
        if updates:
            return f"변경 감지: {', '.join(updates)}"
        return "변경 없음"

    async def run_now(self) -> dict:
        """즉시 1회 실행합니다 (스케줄 무관)."""
        return await self._run_check()
