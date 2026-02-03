# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HIRA 항암화학요법 파일 모니터링 MCP Server — monitors two Korean government healthcare files from HIRA (건강보험심사평가원) for changes in anticancer chemotherapy policies:

1. **허가초과_항암요법** (Off-label Anticancer Therapies) — Excel format
2. **항암화학요법_공고전문** (Anticancer Chemotherapy Announcements) — PDF format

Source URL: https://www.hira.or.kr/bbsDummy.do?pgmid=HIRAA030023030000

Detects file changes via SHA-256 hashing, sends Telegram notifications, and exposes 9 MCP tools for Claude Desktop integration.

## Setup & Commands

```bash
# Install dependencies
pip install -e .
pip install -r requirements.txt
playwright install chromium

# Run MCP server (stdio, for Claude Desktop)
python -m hira_anticancer_mcp_server

# CLI commands
hira-cli check              # Check for file updates
hira-cli check --notify     # Check and always send Telegram notification
hira-cli download            # Download all monitored files
hira-cli download --file-key 허가초과_항암요법   # Download specific file
hira-cli status              # Show current file versions and scheduler state
hira-cli cleanup             # Remove old versioned files
hira-cli daemon              # Run continuous daily scheduler
```

No test suite exists currently.

## Architecture

All source is under `src/hira_anticancer_mcp_server/`. Six modules, all async-first:

| Module | Role |
|--------|------|
| **server.py** | MCP server entry point. Defines 9 tools (`hira_check_updates`, `hira_download_files`, `hira_get_status`, `hira_list_files`, `hira_list_history`, `hira_cleanup`, `hira_scheduler_control`, `hira_read_excel`, `hira_read_pdf`). Routes tool calls via `call_tool()`. |
| **scraper.py** | Playwright-based headless browser scraping. Downloads files from HIRA with multi-URL fallback (2 URLs tried in order). Uses a 6-tier keyword matching system to identify download links across `<a>`, `<button>`, `[onclick]` elements, and iframes. Contains `MetadataStore` class for JSON-based file versioning and SHA-256 hash tracking. |
| **reader.py** | Parses Excel (openpyxl) with merged-cell forward-fill and cancer-type filtering. Parses PDF with a hybrid strategy: pdfplumber for text pages, PyMuPDF for table pages rendered as PNG images. Outputs markdown tables and base64 images. |
| **cli.py** | Argparse-based CLI (`hira-cli`). Wraps scraper/notifier calls in asyncio. |
| **scheduler.py** | Pure-asyncio daily scheduler (no APScheduler dependency). KST timezone-aware. Persists config to `scheduler_config.json`. Singleton pattern via `_get_scheduler()`. |
| **notifier.py** | Sends HTML-formatted Telegram messages via httpx async client. Gracefully degrades when credentials are missing. |

## Key Technical Details

- **Python >=3.10**, build system is **hatchling** (PEP 517)
- **Entry points**: `hira-anticancer-mcp-server` (MCP), `hira-cli` (CLI)
- **Data directory**: `~/.hira-anticancer-data/` stores `metadata.json`, `scheduler_config.json`, and downloaded files (`*_latest.xlsx`, `*_latest.pdf`)
- **Scraper keyword matching** in `scraper.py` uses 6 priority levels (exact text → progressive keyword combinations → single keyword fallback) to reliably find download links on the HIRA page
- **PDF hybrid rendering**: Each page is classified as text or table; table pages are rendered at 150 DPI as PNG via PyMuPDF, with a 50-page chunk limit to prevent token overflow
- **Excel merged cells**: Uses a merge_map forward-fill strategy in `reader.py` to properly handle merged cell regions
- **Download flow**: Files go to a temp directory first, then SHA-256 hash is compared against metadata before moving to final location

## Environment Variables

| Variable | Description |
|----------|-------------|
| `HIRA_DATA_DIR` | Data directory path (default: `~/.hira-anticancer-data`) |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token from BotFather |
| `TELEGRAM_CHAT_ID` | Telegram chat/channel ID for notifications |
