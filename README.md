# 건강보험심사평가원(HIRA) 항암화학요법 공고전문 및 허가초과 항암요법 MCP

> 건강보험심사평가원(HIRA)의 항암화학요법 공고 전문과 허가초과 항암요법 파일을 자동으로 모니터링하고, 새로운 파일이 업데이트되는 경우 자동으로 다운로드하여 이를 기반으로 LLM이 응답하게 합니다 (tool calling 가능한 LLM에서 사용 가능).

## 📋 모니터링 대상

| 파일 | 키 | 형식 | 내용 |
|------|-----|------|------|
| 허가초과 항암요법 | `허가초과_항암요법` | Excel (.xlsx) | 보험 급여 인정 허가초과 항암요법 목록 (다중 시트) |
| 항암화학요법 공고전문 | `항암화학요법_공고전문` | PDF | 항암화학요법 등 공고 내용 전체 문서 |

**출처**: [HIRA 항암화학요법 페이지](https://www.hira.or.kr/bbsDummy.do?pgmid=HIRAA030023030000)

---

## ⚡ 주요 기능

- **자동 변경 감지**: SHA-256 해시 + 파일 크기 비교
- **매일 자동 실행**: 내장 스케줄러 (on/off 가능)
- **MCP 통합**: Claude Desktop에서 직접 사용 가능한 9개 Tool
- **파일 리더**: Excel 머지셀 처리 + PDF 하이브리드 파싱 (텍스트/이미지)
- **CLI 지원**: cron / Task Scheduler에서 단독 실행
- **구파일 자동 정리**: 최신 파일만 보존
- **크로스 플랫폼**: Mac / Windows / Linux

---

## 🚀 설치

### 1. 기본 설치

```bash
git clone https://github.com/junhwankimmd/hira_chemotherapy_mcp.git
cd hira_chemotherapy_mcp

# 의존성 설치
pip install -e .

# Playwright 브라우저 설치
playwright install chromium
```

### 2. 환경변수 설정 (선택)

```env
HIRA_DATA_DIR=~/.hira-anticancer-data
```

---

## 📖 사용법

### CLI 사용

```bash
# 업데이트 확인 (변경 시 자동 다운로드)
hira-cli check

# 전체 파일 다운로드
hira-cli download

# 특정 파일만 다운로드
hira-cli download --file-key 허가초과_항암요법

# 현재 상태 조회
hira-cli status

# 구파일 정리
hira-cli cleanup

# 데몬 모드 (매일 09:00 KST 자동 실행)
hira-cli daemon
```

### Claude Desktop 연동 (MCP)

`claude_desktop_config.json`에 추가:

**방법 1: Python 직접 실행**
```json
{
  "mcpServers": {
    "hira-anticancer": {
      "command": "python",
      "args": ["-m", "hira_anticancer_mcp_server"],
      "env": {
        "HIRA_DATA_DIR": "~/.hira-anticancer-data"
      }
    }
  }
}
```

**방법 2: uv 사용 (권장)**
```json
{
  "mcpServers": {
    "hira-anticancer": {
      "command": "uv",
      "args": ["--directory", "/path/to/hira-anticancer-mcp-server", "run", "hira-anticancer-mcp-server"]
    }
  }
}
```

### MCP Tools

| Tool | 설명 |
|------|------|
| `hira_check_updates` | 서버 vs 로컬 파일 비교 (SHA-256), 변경 시 자동 다운로드 |
| `hira_download_files` | 지정 파일 또는 전체 다운로드 |
| `hira_get_status` | 모니터링 상태, 파일 정보, 스케줄러 상태 조회 |
| `hira_list_files` | HIRA 페이지 실시간 스캔 |
| `hira_list_history` | 파일 변경 이력 조회 |
| `hira_cleanup` | 구 버전 파일 정리 |
| `hira_scheduler_control` | 스케줄러 on/off, 시각 변경, 즉시 실행 |
| `hira_read_excel` | **📊 Excel 파일 읽기** — 머지셀 자동 처리, 암종별 필터, Markdown 테이블 출력 |
| `hira_read_pdf` | **📄 PDF 하이브리드 읽기** — 텍스트 페이지→텍스트, 테이블 페이지→이미지, 암종/키워드 검색 |

#### 📊 `hira_read_excel` 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `file_key` | string | `허가초과_항암요법` | 읽을 파일 키 |
| `sheet` | string | 인정되고 있는 허가초과 항암요법 | 특정 시트 이름 |
| `cancer_type` | string | (전체) | 암종 필터 (예: `난소암`, `유방암`) |
| `max_rows` | integer | `200` | 최대 반환 행 수 |

#### 📄 `hira_read_pdf` 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `file_key` | string | `항암화학요법_공고전문` | 읽을 파일 키 |
| `cancer_type` | string | - | 암종명으로 페이지 자동 조회 (예: `난소암`, `NSCLC`) |
| `search` | string | - | PDF 전체 키워드 검색 (예: `trastuzumab`) |
| `pages` | string | - | 페이지 범위 (예: `1-10`, `1,3,7-10`) |
| `section` | string | - | 섹션 필터: `일반원칙`, `암종별항암요법`, `항암면역요법제`, `항구토제`, `별표`, `부록` |
| `text_only` | boolean | `false` | `true` 시 이미지 없이 텍스트만 반환 (대용량 조회 시 유용) |

---

## ⏰ 자동 실행 설정

### 내장 데몬 모드 (권장)

```bash
# 프로세스를 계속 유지하며 매일 09:00 KST에 자동 실행
hira-cli daemon

# 백그라운드 실행
nohup hira-cli daemon > /tmp/hira-daemon.log 2>&1 &
```

### 시스템 스케줄러 사용

시스템 스케줄러(cron, launchd, Task Scheduler)로 `hira-cli check`를 주기적으로 실행할 수도 있습니다.

**Linux/Mac (cron)**
```bash
# crontab -e
0 9 * * * /path/to/hira-cli check >> /tmp/hira-check.log 2>&1
```

---

## 📁 데이터 구조

```
~/.hira-anticancer-data/
├── metadata.json                          # 파일 메타데이터 (해시, 크기, 이력)
├── scheduler_config.json                  # 스케줄러 설정 (on/off, 시각)
├── 허가초과_항암요법_latest.xlsx           # 최신 파일 (항상 최신으로 덮어쓰기)
├── 항암화학요법_공고전문_latest.pdf        # 최신 파일
└── (구 버전은 자동 삭제됨)
```

---

## 📄 라이선스

MIT License

Copyright (c) 2026 Junhwan Kim

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
