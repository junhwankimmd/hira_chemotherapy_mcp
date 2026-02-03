"""
HIRA 항암화학요법 공고 페이지 스크래핑 모듈.

대상 URL:
  https://www.hira.or.kr/bbsDummy.do?pgmid=HIRAA030023030000
  (제도·정책 > 약제기준정보 > 암질환 사용약제 및 요법 > 항암화학요법)

모니터링 대상 파일 2종:
  1. 허가초과 항암요법 (Off-label anticancer regimens)
  2. 항암화학요법 등 공고내용 전문 (Full anticancer chemotherapy announcements)

기술적 배경:
  - 다운로드 링크가 JavaScript onclick 이벤트로 처리됨 (#none href)
  - 직접 HTTP 요청으로는 파일 URL을 알 수 없음
  - Playwright headless 브라우저로 JS 실행 후 다운로드 이벤트를 캡처
  - SHA-256 해시로 파일 변경 여부를 판별
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# 상수
# ─────────────────────────────────────────────────────────────────────
TARGET_URL = (
    "https://www.hira.or.kr/bbsDummy.do"
    "?pgmid=HIRAA030023030000"
)

KST = timezone(timedelta(hours=9))

# 파일 식별 — 페이지 내 링크 텍스트에서 아래 키워드가 모두 포함되면 해당 파일
FILE_IDENTIFIERS: dict[str, list[str]] = {
    "허가초과_항암요법": ["허가초과", "항암요법"],
    "항암화학요법_공고전문": ["공고내용", "전문"],
}

# Playwright 브라우저 공통 설정
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


# ─────────────────────────────────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────────────────────────────────
def sha256_of(filepath: Path) -> str:
    """파일의 SHA-256 해시를 반환합니다."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def now_kst() -> str:
    """현재 KST 시각을 ISO 8601 문자열로 반환합니다."""
    return datetime.now(KST).isoformat(timespec="seconds")


def _sanitize(name: str) -> str:
    """파일명에 사용할 수 없는 문자를 제거합니다."""
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


# ─────────────────────────────────────────────────────────────────────
# MetadataStore — 다운로드 이력을 JSON으로 관리
# ─────────────────────────────────────────────────────────────────────
class MetadataStore:
    """
    다운로드된 파일의 메타데이터(해시, 크기, 날짜)를 JSON으로 영속화합니다.

    구조 예시:
    {
      "허가초과_항암요법": {
        "current": {
          "filename": "허가초과항암요법_20250203_143022.xlsx",
          "sha256": "abc123...",
          "size": 123456,
          "downloaded_at": "2025-02-03T14:30:22+09:00",
          "source_text": "허가초과 항암요법(2025.1.15.)"
        },
        "history": [ { ... }, ... ]
      },
      ...
    }
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.meta_path = data_dir / "metadata.json"
        self._data: dict[str, Any] = {}
        self._load()

    # ── persistence ──────────────────────────────────────────────────

    def _load(self) -> None:
        if self.meta_path.exists():
            with open(self.meta_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)

    def _save(self) -> None:
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    # ── accessors ────────────────────────────────────────────────────

    def get_current(self, file_key: str) -> dict | None:
        return self._data.get(file_key, {}).get("current")

    def get_history(self, file_key: str) -> list[dict]:
        return self._data.get(file_key, {}).get("history", [])

    def update(self, file_key: str, record: dict) -> None:
        """새 레코드를 current로 설정하고, 기존 current는 history로 밀어넣습니다."""
        if file_key not in self._data:
            self._data[file_key] = {"current": None, "history": []}

        old_current = self._data[file_key]["current"]
        if old_current is not None:
            self._data[file_key]["history"].insert(0, old_current)

        self._data[file_key]["current"] = record
        self._save()

    def get_all_status(self) -> dict:
        """모든 파일의 현재 상태를 요약합니다."""
        result = {}
        for key in FILE_IDENTIFIERS:
            cur = self.get_current(key)
            hist = self.get_history(key)
            result[key] = {
                "current": cur,
                "total_versions": len(hist) + (1 if cur else 0),
            }
        return result


# ─────────────────────────────────────────────────────────────────────
# Playwright helpers
# ─────────────────────────────────────────────────────────────────────
async def ensure_playwright() -> None:
    """Playwright chromium이 설치되어 있는지 확인하고, 없으면 설치합니다."""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            await browser.close()
    except Exception:
        logger.info("Playwright chromium 설치 중…")
        proc = await asyncio.create_subprocess_exec(
            "playwright", "install", "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()
        logger.info("Playwright chromium 설치 완료")


async def _open_page(playwright_instance, *, accept_downloads: bool = False):
    """브라우저를 열고 HIRA 페이지를 로드합니다. (browser, page) 튜플을 반환."""
    browser = await playwright_instance.chromium.launch(headless=True)
    context = await browser.new_context(
        user_agent=_BROWSER_UA,
        accept_downloads=accept_downloads,
    )
    page = await context.new_page()
    await page.goto(TARGET_URL, wait_until="networkidle", timeout=30_000)
    await page.wait_for_timeout(2_000)  # JS 렌더링 마무리 대기
    return browser, page


def _match_file_key(text: str) -> str | None:
    """링크 텍스트가 어떤 file_key에 해당하는지 판별합니다."""
    for key, keywords in FILE_IDENTIFIERS.items():
        if all(kw in text for kw in keywords):
            return key
    return None


# ─────────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────────
async def scrape_file_list() -> list[dict]:
    """
    HIRA 페이지에서 다운로드 가능한 파일 목록과 링크 텍스트를 추출합니다.

    Returns:
        [
          {
            "file_key": "허가초과_항암요법",
            "link_text": "허가초과 항암요법(2025.1.15.)"
          },
          ...
        ]
    """
    from playwright.async_api import async_playwright

    results: list[dict] = []

    async with async_playwright() as p:
        browser, page = await _open_page(p)

        for link in await page.query_selector_all("a"):
            text = (await link.inner_text()).strip()
            key = _match_file_key(text)
            if key:
                results.append({"file_key": key, "link_text": text})

        await browser.close()

    logger.info(f"스캔 완료 — 감지된 파일 수: {len(results)}")
    return results


async def download_file(
    file_key: str,
    data_dir: Path,
    *,
    timeout_ms: int = 60_000,
) -> dict:
    """
    특정 파일을 headless 브라우저로 클릭-다운로드합니다.

    Args:
        file_key: FILE_IDENTIFIERS 키 (예: "허가초과_항암요법")
        data_dir: 저장 디렉토리
        timeout_ms: 다운로드 대기 타임아웃 (ms)

    Returns:
        {
          "filename": "허가초과항암요법_20250203_143022.xlsx",
          "filepath": "/path/to/versioned_file.xlsx",
          "latest_path": "/path/to/허가초과_항암요법_latest.xlsx",
          "sha256": "abc123…",
          "size": 123456,
          "downloaded_at": "2025-02-03T14:30:22+09:00",
          "source_text": "허가초과 항암요법(2025.1.15.)"
        }
    """
    from playwright.async_api import async_playwright

    data_dir.mkdir(parents=True, exist_ok=True)
    keywords = FILE_IDENTIFIERS[file_key]

    async with async_playwright() as p:
        browser, page = await _open_page(p, accept_downloads=True)

        # 해당 파일의 링크를 찾기
        target_link = None
        link_text = ""
        for link in await page.query_selector_all("a"):
            text = (await link.inner_text()).strip()
            if all(kw in text for kw in keywords):
                target_link = link
                link_text = text
                break

        if target_link is None:
            await browser.close()
            raise FileNotFoundError(
                f"'{file_key}' 에 해당하는 다운로드 링크를 찾을 수 없습니다. "
                "페이지 구조가 변경되었을 수 있습니다."
            )

        logger.info(f"다운로드 시작: [{file_key}] {link_text}")

        # 클릭 + 다운로드 이벤트 대기
        async with page.expect_download(timeout=timeout_ms) as dl_info:
            await target_link.click()

        download = await dl_info.value
        suggested = download.suggested_filename or f"{file_key}.xlsx"

        # 버전 파일명 생성 (날짜 포함)
        ts = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
        safe = _sanitize(suggested)
        stem, ext = os.path.splitext(safe)
        versioned = f"{stem}_{ts}{ext}"

        dest = data_dir / versioned
        await download.save_as(str(dest))
        await browser.close()

        # 해시 & 메타
        file_hash = sha256_of(dest)
        file_size = dest.stat().st_size

        # latest 심볼릭 복사
        latest = data_dir / f"{file_key}_latest{ext}"
        shutil.copy2(str(dest), str(latest))

        record = {
            "filename": versioned,
            "filepath": str(dest),
            "latest_path": str(latest),
            "sha256": file_hash,
            "size": file_size,
            "downloaded_at": now_kst(),
            "source_text": link_text,
        }

        logger.info(
            f"다운로드 완료: {versioned} "
            f"({file_size:,} bytes, hash={file_hash[:16]}…)"
        )
        return record


async def check_for_updates(data_dir: Path) -> dict:
    """
    현재 저장된 파일과 HIRA 서버의 최신 파일을 비교합니다.

    변경이 감지된 파일은 자동으로 다운로드 후 메타데이터를 갱신합니다.

    Returns:
        {
          "checked_at": "2025-02-03T14:30:00+09:00",
          "files": {
            "허가초과_항암요법": {
              "has_update": True,
              "reason": "파일 내용 변경 감지 (SHA-256 불일치)",
              ...
            },
            ...
          }
        }
    """
    store = MetadataStore(data_dir)
    file_results: dict[str, Any] = {}

    for file_key in FILE_IDENTIFIERS:
        current = store.get_current(file_key)
        temp_dir = data_dir / "_temp"

        try:
            temp_dir.mkdir(exist_ok=True)
            new_record = await download_file(file_key, temp_dir)
            new_hash = new_record["sha256"]

            if current is None:
                # 최초 다운로드
                info: dict[str, Any] = {
                    "has_update": True,
                    "reason": "최초 다운로드 (이전 기록 없음)",
                    "current_hash": None,
                    "new_hash": new_hash,
                    "new_size": new_record["size"],
                    "link_text": new_record["source_text"],
                }
            elif current["sha256"] != new_hash:
                info = {
                    "has_update": True,
                    "reason": "파일 내용 변경 감지 (SHA-256 불일치)",
                    "current_hash": current["sha256"],
                    "new_hash": new_hash,
                    "current_size": current["size"],
                    "new_size": new_record["size"],
                    "link_text": new_record["source_text"],
                }
            else:
                info = {
                    "has_update": False,
                    "reason": "변경 없음 (SHA-256 일치)",
                    "current_hash": current["sha256"],
                    "link_text": new_record["source_text"],
                }

            # 업데이트가 있으면 실제 디렉토리로 이동
            if info["has_update"]:
                final = data_dir / new_record["filename"]
                shutil.move(new_record["filepath"], str(final))
                new_record["filepath"] = str(final)

                ext = Path(new_record["filename"]).suffix
                latest = data_dir / f"{file_key}_latest{ext}"
                shutil.copy2(str(final), str(latest))
                new_record["latest_path"] = str(latest)

                store.update(file_key, new_record)

            file_results[file_key] = info

        except Exception as exc:
            logger.error(f"[{file_key}] 업데이트 확인 실패: {exc}")
            file_results[file_key] = {
                "has_update": None,
                "reason": f"오류 발생: {exc}",
                "error": True,
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # 업데이트 후 구파일 정리
    cleanup_old_files(data_dir, keep_latest_only=True)

    return {"checked_at": now_kst(), "files": file_results}


def cleanup_old_files(data_dir: Path, *, keep_latest_only: bool = True) -> dict:
    """
    데이터 디렉토리에서 구 버전 파일을 정리합니다.

    정책:
      - *_latest.* 파일은 항상 보존 (현재 파일의 심볼릭 복사)
      - keep_latest_only=True: latest가 아닌 버전 파일을 모두 삭제
      - metadata.json, scheduler_config.json은 항상 보존

    Returns:
        {"deleted": [...], "kept": [...], "errors": [...]}
    """
    protected_names = {"metadata.json", "scheduler_config.json", ".env"}
    deleted = []
    kept = []
    errors = []

    if not data_dir.exists():
        return {"deleted": [], "kept": [], "errors": ["디렉토리 없음"]}

    store = MetadataStore(data_dir)

    # 현재 파일의 실제 경로 목록
    current_filenames: set[str] = set()
    for file_key in FILE_IDENTIFIERS:
        cur = store.get_current(file_key)
        if cur:
            current_filenames.add(cur["filename"])

    for item in data_dir.iterdir():
        if item.name in protected_names:
            kept.append(item.name)
            continue
        if "_latest" in item.name:
            kept.append(item.name)
            continue
        if item.is_dir():
            continue
        if item.name in current_filenames:
            kept.append(item.name)
            continue

        # 구 버전 → 삭제
        if keep_latest_only:
            try:
                item.unlink()
                deleted.append(item.name)
                logger.info(f"구 파일 삭제: {item.name}")
            except Exception as exc:
                errors.append(f"{item.name}: {exc}")

    if deleted:
        logger.info(f"구 파일 정리 완료: {len(deleted)}개 삭제")
    return {"deleted": deleted, "kept": kept, "errors": errors}
