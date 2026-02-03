#!/usr/bin/env python3
"""
HIRA 항암화학요법 파일 모니터링 — 단독 CLI 실행기.

MCP 서버 없이 직접 실행하여 업데이트 확인 + Telegram 알림을 수행합니다.
cron(Linux/Mac) 또는 작업 스케줄러(Windows)에서 사용합니다.

사용법:
  python -m hira_anticancer_mcp_server.cli check       # 업데이트 확인
  python -m hira_anticancer_mcp_server.cli check --notify  # 항상 알림
  python -m hira_anticancer_mcp_server.cli download     # 전체 다운로드
  python -m hira_anticancer_mcp_server.cli status       # 상태 조회
  python -m hira_anticancer_mcp_server.cli cleanup      # 구파일 정리
  python -m hira_anticancer_mcp_server.cli daemon       # 데몬 모드 (내장 스케줄러)

환경변수:
  HIRA_DATA_DIR         — 데이터 저장 경로 (기본: ~/.hira-anticancer-data)
  TELEGRAM_BOT_TOKEN    — Telegram Bot 토큰
  TELEGRAM_CHAT_ID      — Telegram 채팅 ID
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(
    os.getenv("HIRA_DATA_DIR", "~/.hira-anticancer-data")
).expanduser()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("hira-cli")


async def cmd_check(notify: bool = False) -> None:
    """업데이트 확인 + Telegram 알림."""
    from .scraper import check_for_updates, ensure_playwright
    from .notifier import notify_updates

    await ensure_playwright()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("업데이트 확인 중…")
    results = await check_for_updates(DATA_DIR)

    # 결과 출력
    for key, info in results["files"].items():
        has = info.get("has_update")
        if has is True:
            print(f"🔴 {key}: 변경 감지! — {info.get('reason')}")
        elif has is False:
            print(f"🟢 {key}: 변경 없음")
        else:
            print(f"⚠️ {key}: 확인 실패 — {info.get('reason')}")

    # Telegram
    await notify_updates(results, force=notify)


async def cmd_download(file_key: str | None = None) -> None:
    """파일 다운로드."""
    from .scraper import FILE_IDENTIFIERS, MetadataStore, download_file, \
        ensure_playwright, cleanup_old_files

    await ensure_playwright()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    store = MetadataStore(DATA_DIR)

    keys = [file_key] if file_key else list(FILE_IDENTIFIERS.keys())
    for key in keys:
        logger.info(f"다운로드: {key}")
        record = await download_file(key, DATA_DIR)
        store.update(key, record)
        print(f"✅ {key}: {record['filename']} ({record['size']:,} bytes)")

    cleanup_old_files(DATA_DIR, keep_latest_only=True)


async def cmd_status() -> None:
    """현재 상태 조회."""
    from .scraper import MetadataStore

    store = MetadataStore(DATA_DIR)
    status = store.get_all_status()

    print(f"📊 데이터 디렉토리: {DATA_DIR}")
    print("─" * 40)
    for key, info in status.items():
        cur = info["current"]
        if cur:
            print(f"📁 {key}")
            print(f"   파일: {cur['filename']}")
            print(f"   크기: {cur['size']:,} bytes")
            print(f"   해시: {cur['sha256'][:16]}…")
            print(f"   다운로드: {cur['downloaded_at']}")
        else:
            print(f"📁 {key} — (파일 없음)")


async def cmd_cleanup() -> None:
    """구파일 정리."""
    from .scraper import cleanup_old_files

    result = cleanup_old_files(DATA_DIR, keep_latest_only=True)
    if result["deleted"]:
        print(f"🧹 {len(result['deleted'])}개 삭제:")
        for d in result["deleted"]:
            print(f"  ✗ {d}")
    else:
        print("삭제할 구파일 없음")


async def cmd_daemon() -> None:
    """데몬 모드 — 내장 스케줄러로 매일 자동 실행."""
    from .scraper import ensure_playwright
    from .scheduler import HiraScheduler

    await ensure_playwright()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    scheduler = HiraScheduler(DATA_DIR)
    scheduler.enable()
    await scheduler.start()

    print(f"🔄 데몬 모드 시작 — {scheduler.get_status()['schedule']}")
    print("종료하려면 Ctrl+C를 누르세요.")

    try:
        # 영구 대기
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        print("\n데몬 종료…")
        await scheduler.stop()


def main():
    parser = argparse.ArgumentParser(
        description="HIRA 항암화학요법 파일 모니터링 CLI"
    )
    sub = parser.add_subparsers(dest="command", help="실행할 명령")

    # check
    p_check = sub.add_parser("check", help="업데이트 확인")
    p_check.add_argument("--notify", action="store_true",
                         help="변경 없어도 Telegram 알림 전송")

    # download
    p_dl = sub.add_parser("download", help="파일 다운로드")
    p_dl.add_argument("--file-key", type=str, default=None,
                      help="특정 파일만 다운로드")

    # status
    sub.add_parser("status", help="현재 상태 조회")

    # cleanup
    sub.add_parser("cleanup", help="구파일 정리")

    # daemon
    sub.add_parser("daemon", help="데몬 모드 (내장 스케줄러)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "check":
        asyncio.run(cmd_check(notify=args.notify))
    elif args.command == "download":
        asyncio.run(cmd_download(file_key=args.file_key))
    elif args.command == "status":
        asyncio.run(cmd_status())
    elif args.command == "cleanup":
        asyncio.run(cmd_cleanup())
    elif args.command == "daemon":
        asyncio.run(cmd_daemon())


if __name__ == "__main__":
    main()
