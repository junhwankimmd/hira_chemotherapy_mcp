# 🏥 HIRA 항암화학요법 파일 모니터링 MCP Server

> 건강보험심사평가원(HIRA)의 항암화학요법 관련 공고 파일을 자동으로 모니터링하고, 변경 감지 시 Telegram으로 알림합니다.

## 📋 모니터링 대상

| 파일 | 키 | 형식 | 내용 |
|------|-----|------|------|
| 허가초과 항암요법 | `허가초과_항암요법` | Excel (.xlsx) | 보험 급여 인정 허가초과 항암요법 목록 (다중 시트) |
| 항암화학요법 공고전문 | `항암화학요법_공고전문` | PDF | 항암화학요법 등 공고 내용 전체 문서 |

**출처**: [HIRA 항암화학요법 페이지](https://www.hira.or.kr/bbsDummy.do?pgmid=HIRAA030023030000)

---

## ⚡ 주요 기능

- **자동 변경 감지**: SHA-256 해시 + 파일 크기 비교
- **Telegram 알림**: 변경 감지 시 즉시 알림
- **매일 자동 실행**: 내장 스케줄러 (on/off 가능) 또는 GitHub Actions
- **MCP 통합**: Claude Desktop에서 직접 사용 가능한 9개 Tool
- **파일 리더**: Excel 머지셀 처리 + PDF 하이브리드 파싱 (텍스트/이미지)
- **CLI 지원**: cron / Task Scheduler에서 단독 실행
- **구파일 자동 정리**: 최신 파일만 보존
- **크로스 플랫폼**: Mac / Windows / Linux

---

## 🚀 설치

### 1. 기본 설치

```bash
git clone https://github.com/your-repo/hira-anticancer-mcp-server.git
cd hira-anticancer-mcp-server

# 의존성 설치
pip install -r requirements.txt
pip install -e .

# Playwright 브라우저 설치
playwright install chromium
```

### 2. 환경변수 설정

```bash
cp .env.example .env
# .env 파일을 편집하여 Telegram 설정 입력
```

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=987654321
HIRA_DATA_DIR=~/.hira-anticancer-data
```

### Telegram Bot 설정 방법

1. Telegram에서 [@BotFather](https://t.me/botfather)에게 `/newbot` 전송
2. 봇 이름 입력 → **토큰** 발급 → `TELEGRAM_BOT_TOKEN`에 입력
3. 생성된 봇에게 아무 메시지 전송
4. `https://api.telegram.org/bot<TOKEN>/getUpdates` 접속
5. `chat.id` 값 → `TELEGRAM_CHAT_ID`에 입력

---

## 📖 사용법

### CLI 사용

```bash
# 업데이트 확인 (변경 시 자동 다운로드 + Telegram 알림)
hira-cli check

# 변경 없어도 Telegram 알림 전송
hira-cli check --notify

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
        "HIRA_DATA_DIR": "~/.hira-anticancer-data",
        "TELEGRAM_BOT_TOKEN": "your-token",
        "TELEGRAM_CHAT_ID": "your-chat-id"
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
      "args": ["--directory", "/path/to/hira-anticancer-mcp-server", "run", "hira-anticancer-mcp-server"],
      "env": {
        "TELEGRAM_BOT_TOKEN": "your-token",
        "TELEGRAM_CHAT_ID": "your-chat-id"
      }
    }
  }
}
```

### MCP Tools

| Tool | 설명 |
|------|------|
| `hira_check_updates` | 서버 vs 로컬 파일 비교 (SHA-256), 변경 시 자동 다운로드 + 알림 |
| `hira_download_files` | 지정 파일 또는 전체 다운로드 |
| `hira_get_status` | 모니터링 상태, 파일 정보, 스케줄러 상태 조회 |
| `hira_list_files` | HIRA 페이지 실시간 스캔 |
| `hira_list_history` | 파일 변경 이력 조회 |
| `hira_cleanup` | 구 버전 파일 정리 |
| `hira_scheduler_control` | 스케줄러 on/off, 시각 변경, 즉시 실행 |
| `hira_read_excel` | **📊 Excel 파일 읽기** — 머지셀 자동 처리, 암종별 필터, Markdown 테이블 출력 |
| `hira_read_pdf` | **📄 PDF 하이브리드 읽기** — 텍스트 페이지→텍스트, 테이블 페이지→이미지(DPI 150), 섹션 탐색 |

#### 📊 `hira_read_excel` 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `file_key` | string | `허가초과_항암요법` | 읽을 파일 키 |
| `sheet` | string | (활성 시트) | 특정 시트 이름 |
| `cancer_type` | string | (전체) | 암종 필터 (예: `난소암`, `유방암`) |
| `max_rows` | integer | `200` | 최대 반환 행 수 |

#### 📄 `hira_read_pdf` 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `file_key` | string | `항암화학요법_공고전문` | 읽을 파일 키 |
| `pages` | string | (처음 50p) | 페이지 범위 (예: `1-10`, `1,3,7-10`) |
| `section` | string | (없음) | 섹션 필터: `개요`, `급여기준`, `약제목록`, `별표`, `부록` |

---

## ⏰ 자동 실행 설정

### 방법 A: GitHub Actions (무료 추천 ⭐)

> 별도 서버 없이 **완전 무료**로 매일 자동 실행됩니다.

1. 이 레포지토리를 GitHub에 push
2. **Settings → Secrets and variables → Actions**에서 Secrets 추가:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. 매일 09:00 KST에 자동 실행됨

**수동 실행**: Actions 탭 → "HIRA Daily Check" → "Run workflow"

**무료 제한**: GitHub Free 기준 월 2,000분 (매일 1회 ≈ 월 30분 사용으로 충분)

### 방법 B: Mac — launchd

```bash
# ~/Library/LaunchAgents/com.hira.anticancer.check.plist 생성
cat > ~/Library/LaunchAgents/com.hira.anticancer.check.plist << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hira.anticancer.check</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/env</string>
        <string>python3</string>
        <string>-m</string>
        <string>hira_anticancer_mcp_server.cli</string>
        <string>check</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>EnvironmentVariables</key>
    <dict>
        <key>TELEGRAM_BOT_TOKEN</key>
        <string>your-token</string>
        <key>TELEGRAM_CHAT_ID</key>
        <string>your-chat-id</string>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/hira-check.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/hira-check.err</string>
</dict>
</plist>
PLIST

# 등록
launchctl load ~/Library/LaunchAgents/com.hira.anticancer.check.plist

# 해제 (off)
launchctl unload ~/Library/LaunchAgents/com.hira.anticancer.check.plist
```

### 방법 C: Windows — 작업 스케줄러

```powershell
# PowerShell (관리자)
$action = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "-m hira_anticancer_mcp_server.cli check"
$trigger = New-ScheduledTaskTrigger -Daily -At "09:00"
Register-ScheduledTask `
    -TaskName "HIRA_Anticancer_Check" `
    -Action $action `
    -Trigger $trigger `
    -Description "HIRA 항암화학요법 파일 변경 모니터링"

# 비활성화 (off)
Disable-ScheduledTask -TaskName "HIRA_Anticancer_Check"

# 재활성화 (on)
Enable-ScheduledTask -TaskName "HIRA_Anticancer_Check"
```

### 방법 D: 내장 데몬 모드

```bash
# 프로세스를 계속 유지하며 매일 자동 실행
hira-cli daemon

# 또는 nohup으로 백그라운드 실행
nohup hira-cli daemon > /tmp/hira-daemon.log 2>&1 &
```

---

## 🆓 무료 서버 옵션

| 서비스 | 무료 한도 | 적합성 | 비고 |
|--------|-----------|--------|------|
| **GitHub Actions** ⭐ | 월 2,000분 | ✅ 최적 | 설정 가장 간단, 이미 워크플로우 포함 |
| Oracle Cloud Free | 영구 무료 ARM 인스턴스 | ✅ 데몬 모드 가능 | 4 OCPU + 24GB RAM |
| Google Cloud Run | 월 200만 요청 | ⚠️ 과잉 | 컨테이너 필요 |
| Render.com | cron job 무료 | ✅ 괜찮음 | 빌드 시간 제한 있음 |
| Railway.app | $5 크레딧 | ⚠️ 단기 | 크레딧 소진 후 유료 |

**추천**: GitHub Actions가 설정이 가장 쉽고 완전 무료입니다.

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

## 🤖 LLM에서 파일 활용 전략

### 문제

| 파일 | 형식 | 특성 | LLM 직접 입력 가능? |
|------|------|------|---------------------|
| 허가초과 항암요법 | Excel (다중 시트) | 여러 시트, 복잡한 구조 | ⚠️ 시트별 처리 필요 |
| 항암화학요법 공고전문 | PDF (장문) | 수십~수백 페이지 | ⚠️ 토큰 한도 주의 |

### 권장 전략

#### 1. 내장 MCP 리더 Tool (추천 ⭐⭐⭐)

**v0.3.0부터 `hira_read_excel` / `hira_read_pdf` Tool이 내장되어 있어**, 파일 업로드 없이 Claude가 직접 호출하여 파일 내용을 읽을 수 있습니다.

```
사용자: "난소암 관련 허가초과 항암요법 목록을 보여줘"

Claude → hira_read_excel(cancer_type="난소암")
       → Markdown 테이블로 즉시 응답
```

```
사용자: "항암화학요법 공고전문 급여기준 부분을 읽어줘"

Claude → hira_read_pdf(section="급여기준")
       → 텍스트 + 테이블 이미지 혼합 응답
```

**장점**:
- 수동 업로드 불필요
- Excel: 머지셀 자동 처리 + 암종별 필터링
- PDF: 텍스트/테이블 자동 구분, 섹션별 탐색
- 50페이지 자동 청킹으로 토큰 한도 안전

#### 2. Claude의 네이티브 파일 처리 (간편 ⭐⭐)

**Claude 4.x (Opus/Sonnet)** 는 대용량 컨텍스트 윈도우(200K tokens)를 지원하며, PDF와 Excel을 직접 업로드하여 사용할 수 있습니다.

```
Claude Desktop / claude.ai에서:
  📎 클립 버튼 → 허가초과_항암요법_latest.xlsx 업로드
  → "이 파일에서 난소암 관련 허가초과 항암요법을 정리해줘"
```

- **PDF**: Claude가 네이티브로 PDF를 비전(vision)으로 읽음 → 정보 누락 최소
- **Excel**: Claude가 시트별 내용을 파싱 → 다중 시트도 인식 가능

**단점**: 매번 수동 업로드 필요. MCP 리더 Tool이 있으므로 자동화 권장.

#### 3. RAG (Retrieval-Augmented Generation) (대규모 ⭐)

PDF가 수백 페이지인 경우, 전체를 컨텍스트에 넣기 어렵습니다:

```
PDF/Excel → 청킹 → 임베딩 → 벡터 DB → MCP Tool로 검색
```

- **Embedding**: `text-embedding-3-small` (OpenAI) 또는 로컬 모델
- **Vector DB**: ChromaDB (로컬, 무료) 또는 Qdrant
- **검색**: 사용자 질문 관련 청크만 컨텍스트에 주입

**단, 이 프로젝트의 파일 규모(~수십 페이지)에서는 전략 1~2로 충분합니다.**

#### 4. Notion 연동 (문서 관리 ⭐⭐)

파일 내용을 Notion DB에 동기화하면, Claude의 Notion MCP 커넥터로 자연스럽게 접근 가능:

```
HIRA 파일 다운로드 → 파싱 → Notion DB에 upsert → Claude가 Notion 검색으로 접근
```

### 추천 조합

| 사용 시나리오 | 추천 전략 |
|--------------|-----------|
| 일상적 사용 (Claude Desktop) | **전략 1 (MCP 리더 Tool) ✅** |
| MCP 미사용 시 1회성 확인 | 전략 2 (Claude에 직접 업로드) |
| 수백 페이지 PDF 심층 분석 | 전략 3 (RAG) |
| 팀 공유 + 이력 관리 | 전략 4 (Notion 연동) |

---

## 🔧 개발

```bash
# 개발 모드 설치
pip install -e ".[dev]"

# MCP 서버 직접 실행 (디버그)
python -m hira_anticancer_mcp_server

# CLI 실행
python -m hira_anticancer_mcp_server.cli check
```

---

## 📄 라이선스

MIT License
