"""
건강보험심사평가원(HIRA) 항암화학요법 MCP Server.

Claude Desktop / LLM에서 사용 가능한 MCP Tool을 제공합니다.

Tools:
  1. hira_check_updates   — 서버의 최신 파일과 로컬 파일 비교 (SHA-256)
  2. hira_download_files   — 최신 파일 다운로드
  3. hira_get_status        — 현재 모니터링 상태 조회
  4. hira_list_files        — HIRA 페이지의 파일 목록 스캔
  5. hira_list_history      — 파일 변경 이력 조회
  6. hira_cleanup           — 구 버전 파일 정리
  7. hira_scheduler_control — 스케줄러 on/off/상태/즉시실행
  8. hira_read_excel        — Excel 파일 읽기 (머지셀 처리, 암종 필터)
  9. hira_read_pdf          — PDF 하이브리드 읽기 (텍스트+이미지, 섹션 탐색)

Transport: stdio (Claude Desktop 표준)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import ImageContent, TextContent, Tool

from .scraper import (
    FILE_IDENTIFIERS,
    MetadataStore,
    check_for_updates,
    cleanup_old_files,
    download_file,
    ensure_playwright,
    scrape_file_list,
)
from .scheduler import HiraScheduler
from .reader import read_excel, read_pdf

# ─────────────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────────────
load_dotenv()

DATA_DIR = Path(
    os.getenv("HIRA_DATA_DIR", "~/.hira-anticancer-data")
).expanduser()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("hira-mcp-server")

# ─────────────────────────────────────────────────────────────────────
# MCP Server 인스턴스
# ─────────────────────────────────────────────────────────────────────
server = Server("hira-anticancer-mcp-server")
_scheduler: HiraScheduler | None = None


def _get_scheduler() -> HiraScheduler:
    """싱글톤 스케줄러를 반환합니다."""
    global _scheduler
    if _scheduler is None:
        _scheduler = HiraScheduler(DATA_DIR)
    return _scheduler


# ─────────────────────────────────────────────────────────────────────
# Tool 목록 등록
# ─────────────────────────────────────────────────────────────────────
TOOLS = [
    Tool(
        name="hira_check_updates",
        description=(
            "HIRA 심사평가원의 항암화학요법 공고 파일(허가초과 항암요법, "
            "항암화학요법 공고전문)을 서버에서 다운로드하여 로컬 파일과 "
            "SHA-256 해시/크기를 비교합니다. 변경 감지 시 자동 다운로드합니다."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="hira_download_files",
        description=(
            "HIRA 페이지에서 지정된 파일을 다운로드합니다. "
            "file_key를 생략하면 모든 모니터링 대상 파일을 다운로드합니다."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_key": {
                    "type": "string",
                    "description": (
                        "다운로드할 파일 키. 가능한 값: "
                        "허가초과_항암요법, 항암화학요법_공고전문. "
                        "생략 시 전체 다운로드"
                    ),
                },
            },
        },
    ),
    Tool(
        name="hira_get_status",
        description=(
            "현재 모니터링 상태를 조회합니다: 각 파일의 최신 버전, "
            "해시값, 크기, 마지막 확인 시각, 스케줄러 상태 등"
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="hira_list_files",
        description=(
            "HIRA 항암화학요법 페이지를 실시간으로 스캔하여 "
            "다운로드 가능한 파일 목록과 링크 텍스트를 반환합니다."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="hira_list_history",
        description="특정 파일의 변경 이력(다운로드 히스토리)을 조회합니다.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_key": {
                    "type": "string",
                    "description": (
                        "조회할 파일 키: 허가초과_항암요법 또는 항암화학요법_공고전문"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "최대 반환 개수 (기본 10)",
                    "default": 10,
                },
            },
            "required": ["file_key"],
        },
    ),
    Tool(
        name="hira_cleanup",
        description=(
            "데이터 디렉토리에서 구 버전 파일을 정리합니다. "
            "최신(current) 파일과 *_latest 파일만 보존합니다."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="hira_scheduler_control",
        description=(
            "매일 자동 업데이트 확인 스케줄러를 제어합니다. "
            "활성화/비활성화, 시각 변경, 즉시 실행, 상태 조회가 가능합니다."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "enable", "disable", "run_now", "set_time"],
                    "description": (
                        "status: 상태 조회, enable: 활성화(ON), "
                        "disable: 비활성화(OFF), "
                        "run_now: 즉시 1회 실행, "
                        "set_time: 체크 시각 변경"
                    ),
                },
                "hour": {
                    "type": "integer",
                    "description": "set_time 시 사용할 시(0-23, KST)",
                },
                "minute": {
                    "type": "integer",
                    "description": "set_time 시 사용할 분(0-59)",
                    "default": 0,
                },
            },
            "required": ["action"],
        },
    ),
    # ── 파일 리더 Tool ──────────────────────────────────────────
    Tool(
        name="hira_read_excel",
        description=(
            "다운로드된 HIRA 허가초과 항암요법 Excel 파일을 읽습니다. "
            "기본적으로 '인정되고 있는 허가초과 항암요법(용법용량포함)' 시트를 읽으며, "
            "암종별 필터링을 지원합니다. 결과는 Markdown 테이블로 반환됩니다.\n\n"
            "⚠️ 중요: 기본 시트('인정되고 있는 허가초과 항암요법')에서 먼저 검색하세요. "
            "다른 시트를 조회하기 전에 반드시 사용자에게 어떤 시트를 원하는지 확인하세요.\n\n"
            "시트 목록:\n"
            "- 인정되고 있는 허가초과 항암요법(용법용량포함): 승인된 허가초과 요법 (기본)\n"
            "- 검토중인 허가초과 항암요법: ⚠️ 아직 승인되지 않음, 검토 중\n"
            "- 불승인 요법: ⚠️ 승인 거부됨, 급여 불인정\n"
            "- 안내: 파일 안내 정보\n"
            "- 허가초과 항암요법 변경대비표: 변경 이력"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_key": {
                    "type": "string",
                    "description": (
                        "읽을 파일 키. 기본: '허가초과_항암요법'. "
                        "가능한 값: 허가초과_항암요법, 항암화학요법_공고전문"
                    ),
                    "default": "허가초과_항암요법",
                },
                "sheet": {
                    "type": "string",
                    "description": (
                        "시트 이름. 생략 시 '인정되고 있는 허가초과 항암요법(용법용량포함)' "
                        "시트를 자동 선택합니다. "
                        "다른 시트 조회 전 사용자 확인 필수!"
                    ),
                },
                "cancer_type": {
                    "type": "string",
                    "description": (
                        "암종 필터 키워드 (예: '난소암', '자궁경부암', "
                        "'유방암', '폐암'). 생략 시 전체 데이터"
                    ),
                },
                "max_rows": {
                    "type": "integer",
                    "description": "최대 반환 행 수 (기본 200, 토큰 제한 방지)",
                    "default": 200,
                },
            },
        },
    ),
    Tool(
        name="hira_read_pdf",
        description=(
            "다운로드된 HIRA 항암화학요법 공고전문 PDF(274p)를 읽습니다. "
            "추천 사용법: (1) cancer_type으로 암종별 페이지 자동 조회, "
            "(2) search로 약제명/키워드 검색, (3) pages로 특정 페이지 직접 열람. "
            "파라미터 없이 호출하면 목차(암종별 페이지 매핑)를 반환합니다. "
            "테이블 페이지는 이미지로, 텍스트 페이지는 텍스트로 반환합니다. "
            "넓은 범위 조회 시 text_only=true로 1MB 제한을 회피할 수 있습니다."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_key": {
                    "type": "string",
                    "description": (
                        "읽을 파일 키. 기본: '항암화학요법_공고전문'. "
                        "가능한 값: 허가초과_항암요법, 항암화학요법_공고전문"
                    ),
                    "default": "항암화학요법_공고전문",
                },
                "cancer_type": {
                    "type": "string",
                    "description": (
                        "암종명으로 해당 페이지 범위를 자동 조회합니다. "
                        "한글/영문 모두 지원. "
                        "예: '난소암', 'ovarian', '유방암', 'breast', "
                        "'비소세포폐암', 'NSCLC'"
                    ),
                },
                "search": {
                    "type": "string",
                    "description": (
                        "PDF 전체에서 키워드를 검색합니다. "
                        "약제명, 암종명, 요법명 등으로 검색 가능. "
                        "예: 'trastuzumab deruxtecan', 'pembrolizumab', '난소암'"
                    ),
                },
                "pages": {
                    "type": "string",
                    "description": (
                        "페이지 범위 (예: '1-10', '5', '1,3,7-10'). 1-indexed. "
                        "테이블이 많은 범위는 2~3p씩 요청 권장."
                    ),
                },
                "section": {
                    "type": "string",
                    "description": (
                        "섹션 필터. 가능한 값: "
                        "일반원칙, 암종별항암요법, 항암면역요법제, 항구토제, 별표, 부록"
                    ),
                },
                "text_only": {
                    "type": "boolean",
                    "description": (
                        "true로 설정하면 이미지 없이 텍스트만 반환합니다. "
                        "넓은 페이지 범위 조회 시 1MB 제한 회피에 유용합니다."
                    ),
                    "default": False,
                },
            },
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


# ─────────────────────────────────────────────────────────────────────
# Tool 실행 핸들러
# ─────────────────────────────────────────────────────────────────────
def _to_text(data: Any) -> list[TextContent]:
    """결과를 MCP TextContent로 변환합니다."""
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent]:
    """등록된 MCP Tool을 실행합니다."""
    logger.info(f"Tool 호출: {name}({arguments})")

    try:
        if name == "hira_check_updates":
            return await _handle_check_updates(arguments)
        elif name == "hira_download_files":
            return await _handle_download_files(arguments)
        elif name == "hira_get_status":
            return await _handle_get_status(arguments)
        elif name == "hira_list_files":
            return await _handle_list_files(arguments)
        elif name == "hira_list_history":
            return await _handle_list_history(arguments)
        elif name == "hira_cleanup":
            return await _handle_cleanup(arguments)
        elif name == "hira_scheduler_control":
            return await _handle_scheduler(arguments)
        elif name == "hira_read_excel":
            return await _handle_read_excel(arguments)
        elif name == "hira_read_pdf":
            return await _handle_read_pdf(arguments)
        else:
            return _to_text(f"알 수 없는 도구: {name}")
    except Exception as exc:
        logger.error(f"Tool 실행 오류 [{name}]: {exc}", exc_info=True)
        return _to_text(f"⚠️ 오류 발생: {exc}")


# ─────────────────────────────────────────────────────────────────────
# 개별 Tool 핸들러
# ─────────────────────────────────────────────────────────────────────
async def _handle_check_updates(args: dict) -> list[TextContent]:
    """hira_check_updates 실행"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    results = await check_for_updates(DATA_DIR)

    # 사람이 읽기 좋은 요약 생성
    summary_lines = [
        "📋 HIRA 항암화학요법 파일 업데이트 확인 결과",
        f"확인 시각: {results['checked_at']}",
        "─" * 40,
    ]
    for key, info in results["files"].items():
        has = info.get("has_update")
        if has is True:
            summary_lines.append(f"🔴 {key}: 변경 감지!")
            summary_lines.append(f"   → {info.get('reason')}")
            if info.get("new_size"):
                summary_lines.append(f"   크기: {info['new_size']:,} bytes")
        elif has is False:
            summary_lines.append(f"🟢 {key}: 변경 없음")
        else:
            summary_lines.append(f"⚠️ {key}: 확인 실패 — {info.get('reason')}")
    summary_lines.append("─" * 40)

    return _to_text("\n".join(summary_lines))


async def _handle_download_files(args: dict) -> list[TextContent]:
    """hira_download_files 실행"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    store = MetadataStore(DATA_DIR)

    file_key = args.get("file_key")
    keys = [file_key] if file_key else list(FILE_IDENTIFIERS.keys())

    results = []
    for key in keys:
        if key not in FILE_IDENTIFIERS:
            results.append(f"⚠️ 알 수 없는 파일 키: {key}")
            continue

        record = await download_file(key, DATA_DIR)
        store.update(key, record)
        results.append(
            f"✅ {key} 다운로드 완료\n"
            f"   파일: {record['filename']}\n"
            f"   크기: {record['size']:,} bytes\n"
            f"   SHA-256: {record['sha256'][:16]}…"
        )

    # 구파일 정리
    cleanup_old_files(DATA_DIR, keep_latest_only=True)

    return _to_text("\n\n".join(results))


async def _handle_get_status(args: dict) -> list[TextContent]:
    """hira_get_status 실행"""
    store = MetadataStore(DATA_DIR)
    status = store.get_all_status()
    scheduler = _get_scheduler()
    sched_status = scheduler.get_status()

    lines = [
        "📊 HIRA 항암화학요법 모니터링 현황",
        f"데이터 디렉토리: {DATA_DIR}",
        "─" * 40,
    ]

    for key, info in status.items():
        cur = info["current"]
        lines.append(f"📁 {key}")
        if cur:
            lines.append(f"   최신 파일: {cur['filename']}")
            lines.append(f"   크기: {cur['size']:,} bytes")
            lines.append(f"   SHA-256: {cur['sha256'][:16]}…")
            lines.append(f"   다운로드: {cur['downloaded_at']}")
            lines.append(f"   출처 텍스트: {cur.get('source_text', '?')}")
        else:
            lines.append("   (아직 다운로드된 파일 없음)")
        lines.append(f"   총 버전 수: {info['total_versions']}")
        lines.append("")

    lines.append("─" * 40)
    lines.append("⏰ 스케줄러 상태")
    lines.append(f"   활성: {'ON ✅' if sched_status['enabled'] else 'OFF ❌'}")
    lines.append(f"   주기: {sched_status['schedule']}")
    lines.append(f"   다음 실행: {sched_status['next_run_in']}")
    lines.append(f"   마지막 실행: {sched_status.get('last_run', '없음')}")

    return _to_text("\n".join(lines))


async def _handle_list_files(args: dict) -> list[TextContent]:
    """hira_list_files 실행"""
    files = await scrape_file_list()

    if not files:
        return _to_text("HIRA 페이지에서 다운로드 가능한 파일을 찾지 못했습니다.")

    lines = [
        "📄 HIRA 항암화학요법 페이지 파일 목록",
        "─" * 40,
    ]
    for f in files:
        lines.append(f"  • [{f['file_key']}] {f['link_text']}")

    return _to_text("\n".join(lines))


async def _handle_list_history(args: dict) -> list[TextContent]:
    """hira_list_history 실행"""
    file_key = args["file_key"]
    limit = args.get("limit", 10)

    if file_key not in FILE_IDENTIFIERS:
        return _to_text(
            f"알 수 없는 파일 키: {file_key}\n"
            f"가능한 값: {', '.join(FILE_IDENTIFIERS.keys())}"
        )

    store = MetadataStore(DATA_DIR)
    current = store.get_current(file_key)
    history = store.get_history(file_key)[:limit]

    lines = [f"📜 {file_key} 변경 이력", "─" * 40]

    if current:
        lines.append(f"[현재] {current['filename']}")
        lines.append(f"       다운로드: {current['downloaded_at']}")
        lines.append(f"       크기: {current['size']:,} bytes")
        lines.append(f"       SHA-256: {current['sha256'][:16]}…")
    else:
        lines.append("(현재 파일 없음)")

    if history:
        lines.append("")
        lines.append(f"이전 버전 ({len(history)}개):")
        for i, h in enumerate(history, 1):
            lines.append(f"  {i}. {h['filename']} ({h['downloaded_at']})")
    else:
        lines.append("\n(이전 버전 없음)")

    return _to_text("\n".join(lines))


async def _handle_cleanup(args: dict) -> list[TextContent]:
    """hira_cleanup 실행"""
    result = cleanup_old_files(DATA_DIR, keep_latest_only=True)

    lines = ["🧹 구 파일 정리 결과", "─" * 40]
    if result["deleted"]:
        lines.append(f"삭제: {len(result['deleted'])}개")
        for d in result["deleted"]:
            lines.append(f"  ✗ {d}")
    else:
        lines.append("삭제할 구 파일 없음")

    lines.append(f"\n보존: {len(result['kept'])}개")
    for k in result["kept"]:
        lines.append(f"  ✓ {k}")

    if result["errors"]:
        lines.append(f"\n오류: {len(result['errors'])}개")
        for e in result["errors"]:
            lines.append(f"  ⚠️ {e}")

    return _to_text("\n".join(lines))


async def _handle_scheduler(args: dict) -> list[TextContent]:
    """hira_scheduler_control 실행"""
    action = args["action"]
    scheduler = _get_scheduler()

    if action == "status":
        status = scheduler.get_status()
        lines = [
            "⏰ 스케줄러 상태",
            f"  활성: {'ON ✅' if status['enabled'] else 'OFF ❌'}",
            f"  실행 중: {'예' if status['running'] else '아니오'}",
            f"  주기: {status['schedule']}",
            f"  다음 실행: {status['next_run_in']}",
            f"  마지막 실행: {status.get('last_run', '없음')}",
            f"  마지막 결과: {status.get('last_result_summary', '없음')}",
        ]
        return _to_text("\n".join(lines))

    elif action == "enable":
        status = scheduler.enable()
        # 스케줄러가 아직 시작되지 않았으면 시작
        if not scheduler._running:
            await scheduler.start()
        return _to_text("✅ 스케줄러 활성화됨 (ON)\n"
                        f"주기: {status['schedule']}")

    elif action == "disable":
        status = scheduler.disable()
        return _to_text("❌ 스케줄러 비활성화됨 (OFF)\n"
                        "※ 스케줄 루프는 유지되나 실행을 건너뜁니다.")

    elif action == "run_now":
        result = await scheduler.run_now()
        if "error" in result:
            return _to_text(f"⚠️ 즉시 실행 오류: {result['error']}")

        lines = ["🔄 즉시 실행 완료"]
        for key, info in result.get("files", {}).items():
            has = info.get("has_update")
            if has is True:
                lines.append(f"  🔴 {key}: 변경 감지")
            elif has is False:
                lines.append(f"  🟢 {key}: 변경 없음")
            else:
                lines.append(f"  ⚠️ {key}: 확인 실패")
        return _to_text("\n".join(lines))

    elif action == "set_time":
        hour = args.get("hour")
        minute = args.get("minute", 0)
        if hour is None:
            return _to_text("⚠️ hour 파라미터가 필요합니다 (0-23)")
        status = scheduler.set_schedule(hour, minute)
        return _to_text(
            f"✅ 체크 시각 변경: {hour:02d}:{minute:02d} KST\n"
            f"다음 실행: {status['next_run_in']}"
        )

    else:
        return _to_text(
            f"알 수 없는 action: {action}\n"
            "가능한 값: status, enable, disable, run_now, set_time"
        )


# ── 파일 리더 핸들러 ────────────────────────────────────────────

def _resolve_latest_file(file_key: str) -> Path | None:
    """file_key에 대응하는 최신 파일 경로를 찾습니다."""
    if file_key not in FILE_IDENTIFIERS:
        return None

    # MetadataStore에서 latest_path 확인
    store = MetadataStore(DATA_DIR)
    current = store.get_current(file_key)
    if current:
        # latest_path 우선
        latest_path = current.get("latest_path")
        if latest_path and Path(latest_path).exists():
            return Path(latest_path)
        # filepath fallback
        filepath = current.get("filepath")
        if filepath and Path(filepath).exists():
            return Path(filepath)

    # glob fallback: DATA_DIR에서 *_latest.* 패턴
    for ext in [".xlsx", ".xls", ".pdf", ".hwp"]:
        candidate = DATA_DIR / f"{file_key}_latest{ext}"
        if candidate.exists():
            return candidate

    return None


async def _handle_read_excel(args: dict) -> list[TextContent | ImageContent]:
    """hira_read_excel 실행"""
    file_key = args.get("file_key", "허가초과_항암요법")

    filepath = _resolve_latest_file(file_key)
    if filepath is None:
        return _to_text(
            f"⚠️ '{file_key}' 파일을 찾을 수 없습니다.\n"
            f"먼저 hira_download_files로 파일을 다운로드해주세요.\n"
            f"데이터 디렉토리: {DATA_DIR}"
        )

    # 확장자 확인
    if filepath.suffix.lower() not in (".xlsx", ".xls"):
        return _to_text(
            f"⚠️ '{file_key}'의 최신 파일이 Excel 형식이 아닙니다: "
            f"{filepath.name}\n"
            "hira_read_pdf를 사용해주세요."
        )

    logger.info(f"Excel 읽기: {filepath}")
    return read_excel(
        filepath,
        sheet=args.get("sheet"),
        cancer_type=args.get("cancer_type"),
        max_rows=args.get("max_rows", 200),
    )


async def _handle_read_pdf(args: dict) -> list[TextContent | ImageContent]:
    """hira_read_pdf 실행"""
    file_key = args.get("file_key", "항암화학요법_공고전문")

    filepath = _resolve_latest_file(file_key)
    if filepath is None:
        return _to_text(
            f"⚠️ '{file_key}' 파일을 찾을 수 없습니다.\n"
            f"먼저 hira_download_files로 파일을 다운로드해주세요.\n"
            f"데이터 디렉토리: {DATA_DIR}"
        )

    # 확장자 확인
    if filepath.suffix.lower() != ".pdf":
        return _to_text(
            f"⚠️ '{file_key}'의 최신 파일이 PDF 형식이 아닙니다: "
            f"{filepath.name}\n"
            "hira_read_excel을 사용해주세요."
        )

    logger.info(f"PDF 읽기: {filepath}")
    return read_pdf(
        filepath,
        pages=args.get("pages"),
        section=args.get("section"),
        cancer_type=args.get("cancer_type"),
        search=args.get("search"),
        text_only=args.get("text_only", False),
    )


# ─────────────────────────────────────────────────────────────────────
# 서버 진입점
# ─────────────────────────────────────────────────────────────────────
def main() -> None:
    """MCP Server를 stdio transport로 실행합니다."""
    logger.info("HIRA Anticancer MCP Server 시작…")
    logger.info(f"데이터 디렉토리: {DATA_DIR}")

    async def _run():
        # Playwright 사전 확인
        await ensure_playwright()

        # 스케줄러 자동 시작
        scheduler = _get_scheduler()
        if scheduler._enabled:
            await scheduler.start()
            logger.info("스케줄러 자동 시작 완료")

        # MCP stdio 서버 실행
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(_run())


if __name__ == "__main__":
    main()
