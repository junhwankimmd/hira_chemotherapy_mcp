"""
HIRA 항암화학요법 파일 리더.

Excel(허가초과_항암요법)과 PDF(항암화학요법_공고전문)를 파싱하여
MCP TextContent / ImageContent 형태로 반환합니다.

전략:
  - Excel: openpyxl text extraction (머지셀 forward-fill, data_only=True)
  - PDF:   하이브리드 (텍스트 전용 → pdfplumber, 테이블 포함 → PyMuPDF ImageContent)
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import Any

from mcp.types import ImageContent, TextContent

logger = logging.getLogger("hira-mcp-reader")

# ─────────────────────────────────────────────────────────────────────
# Excel 리더 (openpyxl)
# ─────────────────────────────────────────────────────────────────────

def read_excel(
    filepath: Path,
    *,
    sheet: str | None = None,
    cancer_type: str | None = None,
    max_rows: int = 200,
) -> list[TextContent]:
    """
    Excel 파일을 읽어 Markdown 테이블로 변환합니다.

    Args:
        filepath: .xlsx 파일 경로
        sheet: 시트 이름 (None이면 활성 시트)
        cancer_type: 암종 필터 (예: "난소암", "자궁경부암")
        max_rows: 최대 반환 행 수 (토큰 제한 방지)

    Returns:
        list[TextContent] — Markdown 테이블 + 요약 정보
    """
    import openpyxl

    wb = openpyxl.load_workbook(str(filepath), data_only=True, read_only=False)

    if sheet:
        if sheet not in wb.sheetnames:
            return [TextContent(
                type="text",
                text=f"⚠️ 시트 '{sheet}'를 찾을 수 없습니다.\n"
                     f"사용 가능한 시트: {', '.join(wb.sheetnames)}"
            )]
        ws = wb[sheet]
    else:
        ws = wb.active

    # ── 머지셀 forward-fill 맵 구축 ─────────────────────────────
    merge_map: dict[tuple[int, int], Any] = {}
    for merged_range in ws.merged_cells.ranges:
        top_left_value = ws.cell(
            row=merged_range.min_row,
            column=merged_range.min_col,
        ).value
        for row in range(merged_range.min_row, merged_range.max_row + 1):
            for col in range(merged_range.min_col, merged_range.max_col + 1):
                merge_map[(row, col)] = top_left_value

    # ── 데이터 추출 ─────────────────────────────────────────────
    all_rows: list[list[str]] = []
    for row_idx, row in enumerate(ws.iter_rows(values_only=False), start=1):
        cells: list[str] = []
        for cell in row:
            coord = (cell.row, cell.column)
            if coord in merge_map:
                val = merge_map[coord]
            else:
                val = cell.value
            cells.append(str(val).strip() if val is not None else "")
        all_rows.append(cells)

    wb.close()

    if not all_rows:
        return [TextContent(type="text", text="⚠️ 시트에 데이터가 없습니다.")]

    # ── 헤더 감지 (첫 번째 비어있지 않은 행) ────────────────────
    header_idx = 0
    for i, row in enumerate(all_rows):
        if any(c for c in row):
            header_idx = i
            break

    headers = all_rows[header_idx]
    data_rows = all_rows[header_idx + 1:]

    # ── 암종 필터 적용 ──────────────────────────────────────────
    if cancer_type:
        # 주로 C열(index 2) 또는 암종 관련 컬럼에서 필터
        cancer_col_idx = _find_cancer_column(headers)
        if cancer_col_idx is not None:
            data_rows = [
                row for row in data_rows
                if cancer_type in row[cancer_col_idx]
            ]

    total_count = len(data_rows)
    truncated = total_count > max_rows
    data_rows = data_rows[:max_rows]

    # ── Markdown 테이블 생성 ────────────────────────────────────
    md_lines = _to_markdown_table(headers, data_rows)

    # ── 요약 정보 ──────────────────────────────────────────────
    summary_parts = [
        f"📊 시트: {ws.title}",
        f"📏 전체 행: {total_count}행",
    ]
    if cancer_type:
        summary_parts.append(f"🔍 필터: '{cancer_type}'")
    if truncated:
        summary_parts.append(f"⚠️ {max_rows}행까지만 표시 (전체 {total_count}행)")

    summary = " | ".join(summary_parts)

    return [TextContent(type="text", text=f"{summary}\n\n{md_lines}")]


def _find_cancer_column(headers: list[str]) -> int | None:
    """헤더에서 암종 관련 컬럼 인덱스를 찾습니다."""
    cancer_keywords = ["암종", "cancer", "질환", "적응증", "진단"]
    for idx, h in enumerate(headers):
        h_lower = h.lower()
        if any(kw in h_lower for kw in cancer_keywords):
            return idx
    # 기본 fallback: C열 (index 2) — HIRA 엑셀 관행
    if len(headers) > 2:
        return 2
    return None


def _to_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    """헤더와 데이터 행을 Markdown 테이블 문자열로 변환합니다."""
    if not headers:
        return "(빈 테이블)"

    # 열 수 통일
    n_cols = len(headers)

    # 긴 셀 내용 축약 (300자 초과 시)
    def _trunc(s: str, limit: int = 300) -> str:
        return s[:limit] + "…" if len(s) > limit else s

    header_line = "| " + " | ".join(_trunc(h) for h in headers) + " |"
    sep_line = "| " + " | ".join("---" for _ in headers) + " |"

    data_lines = []
    for row in rows:
        # 열 수가 헤더보다 적으면 빈 문자열로 채움
        padded = row[:n_cols] + [""] * max(0, n_cols - len(row))
        line = "| " + " | ".join(_trunc(c) for c in padded) + " |"
        data_lines.append(line)

    return "\n".join([header_line, sep_line] + data_lines)


# ─────────────────────────────────────────────────────────────────────
# PDF 리더 (pdfplumber + PyMuPDF 하이브리드)
# ─────────────────────────────────────────────────────────────────────

# 페이지 타입 감지 상수
_TABLE_THRESHOLD = 1  # pdfplumber가 N개 이상 테이블 감지 시 → 이미지 렌더링
_MAX_PAGES_PER_CALL = 50  # 한 번에 처리할 최대 페이지 (토큰 제한 방지)
_IMAGE_DPI = 150  # ImageContent 해상도

# PDF 섹션별 키워드 매핑 (항암화학요법 공고전문 구조)
PDF_SECTIONS: dict[str, list[str]] = {
    "개요": ["개요", "총칙", "일반원칙"],
    "급여기준": ["급여기준", "요양급여"],
    "약제목록": ["약제", "목록"],
    "별표": ["별표", "[별표"],
    "부록": ["부록", "참고"],
}


def read_pdf(
    filepath: Path,
    *,
    pages: str | None = None,
    section: str | None = None,
) -> list[TextContent | ImageContent]:
    """
    PDF를 하이브리드 방식으로 읽습니다.

    - 텍스트 전용 페이지 → pdfplumber.extract_text() → TextContent
    - 테이블 포함 페이지 → PyMuPDF pixmap(DPI 150) → ImageContent (base64 PNG)

    Args:
        filepath: .pdf 파일 경로
        pages: 페이지 범위 (예: "1-10", "5", "1,3,7-10"). None이면 처음 50p.
        section: 섹션 필터 (예: "개요", "급여기준", "별표"). 키워드로 시작 페이지 탐색.

    Returns:
        list[TextContent | ImageContent] 혼합 리스트
    """
    import fitz  # PyMuPDF
    import pdfplumber

    doc = fitz.open(str(filepath))
    total_pages = len(doc)

    # ── 페이지 범위 결정 ────────────────────────────────────────
    if section:
        page_indices = _find_section_pages(filepath, section, total_pages)
        if not page_indices:
            doc.close()
            return [TextContent(
                type="text",
                text=f"⚠️ 섹션 '{section}'을 찾을 수 없습니다.\n"
                     f"사용 가능한 섹션: {', '.join(PDF_SECTIONS.keys())}\n"
                     f"총 {total_pages}페이지"
            )]
    elif pages:
        page_indices = _parse_page_range(pages, total_pages)
    else:
        # 기본: 처음 50페이지
        page_indices = list(range(min(total_pages, _MAX_PAGES_PER_CALL)))

    # 50페이지 제한 적용
    truncated = len(page_indices) > _MAX_PAGES_PER_CALL
    page_indices = page_indices[:_MAX_PAGES_PER_CALL]

    # ── 페이지별 타입 감지 + 파싱 ─────────────────────────────
    results: list[TextContent | ImageContent] = []

    # 시작 메타 정보
    meta = (
        f"📄 PDF: {filepath.name} ({total_pages}p)\n"
        f"📖 표시 범위: {_format_page_range(page_indices)} "
        f"({len(page_indices)}p)"
    )
    if truncated:
        meta += f"\n⚠️ {_MAX_PAGES_PER_CALL}p 제한 적용됨"
    if section:
        meta += f"\n🔍 섹션 필터: '{section}'"
    results.append(TextContent(type="text", text=meta))

    # pdfplumber로 테이블 감지
    pdf_plumber = pdfplumber.open(str(filepath))

    text_buffer: list[str] = []  # 연속 텍스트 페이지 버퍼

    for page_idx in page_indices:
        page_num = page_idx + 1  # 1-indexed

        # pdfplumber로 테이블 감지
        try:
            plumber_page = pdf_plumber.pages[page_idx]
            tables = plumber_page.find_tables()
            has_tables = len(tables) >= _TABLE_THRESHOLD
        except Exception:
            has_tables = False

        if has_tables:
            # 텍스트 버퍼가 있으면 먼저 flush
            if text_buffer:
                results.append(TextContent(
                    type="text", text="\n\n".join(text_buffer)
                ))
                text_buffer.clear()

            # 테이블 페이지 → 이미지 렌더링 (PyMuPDF)
            try:
                fitz_page = doc[page_idx]
                mat = fitz.Matrix(_IMAGE_DPI / 72, _IMAGE_DPI / 72)
                pix = fitz_page.get_pixmap(matrix=mat)
                png_bytes = pix.tobytes("png")

                b64_data = base64.b64encode(png_bytes).decode("ascii")

                results.append(TextContent(
                    type="text",
                    text=f"--- 📊 p.{page_num} (테이블 포함 → 이미지) ---"
                ))
                results.append(ImageContent(
                    type="image",
                    data=b64_data,
                    mimeType="image/png",
                ))
            except Exception as e:
                logger.warning(f"페이지 {page_num} 이미지 렌더링 실패: {e}")
                # 폴백: 텍스트 추출 시도
                text = _extract_text_safe(plumber_page, page_num)
                text_buffer.append(text)

        else:
            # 텍스트 전용 페이지 → pdfplumber 텍스트 추출
            text = _extract_text_safe(plumber_page, page_num)
            text_buffer.append(text)

    # 남은 텍스트 버퍼 flush
    if text_buffer:
        results.append(TextContent(
            type="text", text="\n\n".join(text_buffer)
        ))

    pdf_plumber.close()
    doc.close()

    return results


def _extract_text_safe(plumber_page, page_num: int) -> str:
    """pdfplumber 페이지에서 안전하게 텍스트를 추출합니다."""
    try:
        text = plumber_page.extract_text() or ""
        if text.strip():
            return f"--- p.{page_num} ---\n{text.strip()}"
        else:
            return f"--- p.{page_num} (빈 페이지) ---"
    except Exception as e:
        return f"--- p.{page_num} (추출 실패: {e}) ---"


def _find_section_pages(
    filepath: Path, section: str, total_pages: int
) -> list[int]:
    """
    PDF에서 섹션 키워드가 포함된 페이지 범위를 탐색합니다.

    전략: 섹션 시작 페이지를 찾은 뒤, 다음 섹션 시작까지의 범위를 반환.
    """
    import pdfplumber

    keywords = PDF_SECTIONS.get(section, [section])

    pdf = pdfplumber.open(str(filepath))
    start_page = None
    end_page = total_pages - 1

    # 1차: 정확한 섹션 키워드로 시작 페이지 탐색
    for i, page in enumerate(pdf.pages):
        text = (page.extract_text() or "").strip()
        if not text:
            continue

        # 페이지의 처음 500자에서 키워드 검색 (제목은 상단에 위치)
        header = text[:500]
        if any(kw in header for kw in keywords):
            start_page = i
            break

    if start_page is None:
        pdf.close()
        return []

    # 2차: 다음 섹션 시작점 탐색 (최대 100페이지 범위)
    other_section_keywords = []
    for sec_name, sec_kws in PDF_SECTIONS.items():
        if sec_name != section:
            other_section_keywords.extend(sec_kws)

    for i in range(start_page + 1, min(start_page + 100, total_pages)):
        text = (pdf.pages[i].extract_text() or "").strip()
        header = text[:500]
        if any(kw in header for kw in other_section_keywords):
            end_page = i - 1
            break

    pdf.close()

    return list(range(start_page, end_page + 1))


def _parse_page_range(pages_str: str, total: int) -> list[int]:
    """
    페이지 범위 문자열을 0-indexed 리스트로 변환합니다.

    지원 형식:
      - "5"       → [4]
      - "1-10"    → [0,1,...,9]
      - "1,3,7-10" → [0,2,6,7,8,9]
    """
    result: list[int] = []
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start = max(int(start_s.strip()) - 1, 0)
            end = min(int(end_s.strip()) - 1, total - 1)
            result.extend(range(start, end + 1))
        else:
            idx = int(part) - 1
            if 0 <= idx < total:
                result.append(idx)

    return sorted(set(result))


def _format_page_range(indices: list[int]) -> str:
    """0-indexed 리스트를 사람이 읽기 좋은 페이지 범위로 변환합니다."""
    if not indices:
        return "(없음)"

    # 연속 구간 탐지
    ranges: list[str] = []
    start = indices[0]
    prev = indices[0]

    for i in indices[1:]:
        if i == prev + 1:
            prev = i
        else:
            if start == prev:
                ranges.append(f"p.{start + 1}")
            else:
                ranges.append(f"p.{start + 1}-{prev + 1}")
            start = i
            prev = i

    if start == prev:
        ranges.append(f"p.{start + 1}")
    else:
        ranges.append(f"p.{start + 1}-{prev + 1}")

    return ", ".join(ranges)
