"""
Telegram 알림 모듈.

HIRA 항암화학요법 파일 변경 감지 시 Telegram Bot API를 통해 알림을 전송합니다.

필요 환경변수:
  TELEGRAM_BOT_TOKEN  — BotFather에서 발급받은 토큰
  TELEGRAM_CHAT_ID    — 알림을 받을 채팅 ID (개인 또는 그룹)

Telegram Bot 설정 방법:
  1. @BotFather에게 /newbot 명령 → 토큰 발급
  2. 봇에게 아무 메시지 전송 후 https://api.telegram.org/bot<TOKEN>/getUpdates → chat_id 확인
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _get_credentials() -> tuple[str, str] | None:
    """환경변수에서 Telegram 인증 정보를 로드합니다."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return None
    return token, chat_id


async def send_telegram(message: str, *, parse_mode: str = "HTML") -> bool:
    """
    Telegram 메시지를 전송합니다.

    Args:
        message: 전송할 텍스트 (HTML 형식 지원)
        parse_mode: "HTML" 또는 "Markdown"

    Returns:
        전송 성공 여부
    """
    creds = _get_credentials()
    if creds is None:
        logger.warning(
            "Telegram 인증 정보 없음 — TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID를 설정하세요."
        )
        return False

    token, chat_id = creds
    url = TELEGRAM_API.format(token=token)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": parse_mode,
                },
            )
            resp.raise_for_status()
            logger.info("Telegram 알림 전송 완료")
            return True
    except httpx.HTTPError as exc:
        logger.error(f"Telegram 전송 실패: {exc}")
        return False


def format_update_message(results: dict[str, Any]) -> str:
    """
    check_for_updates 결과를 Telegram HTML 메시지로 포맷팅합니다.

    Args:
        results: check_for_updates()의 반환값

    Returns:
        HTML 형식의 메시지 문자열
    """
    checked_at = results.get("checked_at", "?")
    files = results.get("files", {})

    lines = [
        "🏥 <b>HIRA 항암화학요법 파일 모니터링</b>",
        f"📅 확인 시각: <code>{checked_at}</code>",
        "",
    ]

    any_update = False
    for key, info in files.items():
        has_update = info.get("has_update")
        if has_update is True:
            any_update = True
            lines.append(f"🔴 <b>{key}</b> — 변경 감지!")
            lines.append(f"   사유: {info.get('reason', '?')}")
            if info.get("current_size") and info.get("new_size"):
                lines.append(
                    f"   크기: {info['current_size']:,} → {info['new_size']:,} bytes"
                )
            lines.append(f"   링크 텍스트: {info.get('link_text', '?')}")
        elif has_update is False:
            lines.append(f"🟢 <b>{key}</b> — 변경 없음")
        else:
            lines.append(f"⚠️ <b>{key}</b> — 확인 실패")
            lines.append(f"   사유: {info.get('reason', '?')}")
        lines.append("")

    if not any_update:
        lines.append("✅ 모든 파일 변경 없음")

    return "\n".join(lines)


async def notify_updates(results: dict[str, Any], *, force: bool = False) -> bool:
    """
    업데이트 결과를 Telegram으로 전송합니다.

    Args:
        results: check_for_updates()의 반환값
        force: True이면 변경 없어도 알림 전송

    Returns:
        전송 성공 여부
    """
    files = results.get("files", {})
    any_update = any(
        info.get("has_update") is True for info in files.values()
    )

    if not any_update and not force:
        logger.info("변경 없음 — Telegram 알림 생략")
        return True  # 에러가 아니므로 True

    msg = format_update_message(results)
    return await send_telegram(msg)
