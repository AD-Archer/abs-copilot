# ABS Insight Copilot (SQLite + FastAPI, Docker Portable)

MCP-first analytics assistant for ABS challenge coaching workflows.

## What This Includes
- Single backend service: `Python + FastAPI + SQLite`
- Canonical analytics views:
  - `v_challenges_enriched`
  - `v_team_kpis`
  - `v_player_kpis`
- MCP-style tool surface:
  - `abs.run_query`
  - `abs.challenge_strategy`
  - `abs.player_report`
  - `abs.weekly_summary`
- Chat endpoint that uses those tools by default
- Lightweight web pages:
  - Team Overview
  - Player Lens
  - Ask ABS Copilot
- Weekly report endpoint that writes Markdown + HTML artifacts
  - Includes executive summary, KPI snapshot, tactical opportunity tables, risk flags, and next-week action plan

## Data Scope
- `abs_challenges.csv`: one row per ABS challenge
- `pitches.csv`: all called pitches from ABS-enabled games
- `players.csv`: player lookup table

## Quick Start (Local)
```bash
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:
- `http://localhost:8000/` (home)
- `http://localhost:8000/team`
- `http://localhost:8000/player`
- `http://localhost:8000/copilot`
- `http://localhost:8000/reports-view`

## Quick Start (Docker)
```bash
docker build -t abs-copilot .
docker run --rm -p 8000:8000 --env-file .env -v "$(pwd)/reports:/app/reports" abs-copilot
```

If no `.env` is present, copy `.env.example` and fill values as needed. LLM vars are optional.

## Environment Variables
- `APP_DB_PATH` (default: `/data/abs_insights.db` in container)
- `RESULT_ROW_LIMIT` (default: `200`)
- `REPORTS_DIR` (default: `/app/reports` in container)
- `LLM_BASE_URL` (optional, OpenAI-compatible endpoint, e.g. `https://generativelanguage.googleapis.com/v1beta/openai`)
- `LLM_API_KEY` (optional)
- `LLM_MODEL` (default: `gemini-3.1-flash-lite-preview`)

## Public HTTP Interfaces
- `POST /chat` → answer + sources + supporting stats + recommended actions
- `GET /dashboard/team/{team}`
- `GET /dashboard/player/{player_id}`
- `GET /dashboard/positions`
- `GET /dashboard/non-challenged`
- `GET /dashboard/challenge-usage`
- `GET /dashboard/officiating-proxy`
- `GET /dashboard/miss-locations`
- `POST /reports/weekly`
- `GET /reports/list`
- `GET /reports/content/{report_name}`

### MCP Server (Default)
- SSE MCP endpoint: `http://localhost:8000/mcp/sse`
- MCP message endpoint: `http://localhost:8000/mcp/messages`
- Compatibility aliases: `/sse` and `/messages` (for clients that start from base URL and legacy fallback)

### Helper Endpoints (for debugging)
- `GET /api/mcp/tools`
- `POST /api/mcp/call`

### Core MCP Tool Names
- `abs_run_query`
- `abs_challenge_strategy`
- `abs_player_report`
- `abs_weekly_summary`
- `abs_position_accuracy`
- `abs_non_challenged_incorrect_calls`
- `abs_challenge_usage`
- `abs_officiating_quality_proxy`
- `abs_miss_location_analysis`

Example:
```bash
curl -s localhost:8000/api/mcp/call \
  -X POST \
  -H 'content-type: application/json' \
  -d '{
    "tool":"abs_challenge_strategy",
    "arguments":{"filters":{"team_name":"Omaha Storm Chasers","role":"catcher"}}
  }'
```

## Testing
```bash
uv run pytest
```

## Notes
- Analytics access is read-only by policy (`SELECT`/`WITH` only; write keywords blocked).
- Result sets are bounded by `RESULT_ROW_LIMIT`.
- Weekly report generation is endpoint-triggered (`POST /reports/weekly`) and can be scheduled by an external cron/invoker.
