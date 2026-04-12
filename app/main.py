from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.analytics import (
    challenge_strategy,
    challenge_usage,
    miss_location_analysis,
    non_challenged_incorrect_calls,
    officiating_quality_proxy,
    player_report,
    position_accuracy,
    run_query,
)
from app.database import fetch_all_dicts, get_connection, initialize_database
from app.llm_client import summarize_with_llm_history
from app.mcp_tools import call_tool, list_tools
from app.mcp_server import mcp
from app.reports import generate_weekly_report
from app.config import settings

app = FastAPI(title="ABS Insight Copilot", version="1.0.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    filters: dict[str, Any] = Field(default_factory=dict)
    history: list[ChatTurn] = Field(default_factory=list)


class ToolCallRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class WeeklyReportRequest(BaseModel):
    team_name: str
    week_start: date


@app.on_event("startup")
def on_startup() -> None:
    initialize_database(base_path=Path("."))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sse")
def mcp_legacy_sse_alias() -> RedirectResponse:
    # Compatibility alias for clients that use root URL and then fallback to legacy SSE.
    return RedirectResponse(url="/mcp/sse", status_code=307)


@app.api_route("/messages", methods=["GET", "POST"])
@app.api_route("/messages/", methods=["GET", "POST"])
def mcp_legacy_messages_alias() -> RedirectResponse:
    # Compatibility alias for legacy SSE message posting.
    return RedirectResponse(url="/mcp/messages", status_code=307)


@app.get("/api/mcp/tools")
def api_mcp_tools() -> dict[str, Any]:
    return {"tools": list_tools()}


@app.post("/api/mcp/call")
def api_mcp_call(req: ToolCallRequest) -> dict[str, Any]:
    try:
        result = call_tool(req.tool, req.arguments)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "tool": result.tool,
        "summary": result.summary,
        "data": result.data,
        "recommended_actions": result.recommended_actions,
    }


def _select_tool(question: str) -> tuple[str, dict[str, Any]]:
    q = question.lower()
    team_name = _find_team_in_question(question)
    if team_name and "player" not in q:
        return "abs_challenge_strategy", {"filters": {"team_name": team_name}}
    if "position" in q and ("correct" in q or "incorrect" in q or "accuracy" in q):
        return "abs_position_accuracy", {"filters": {}}
    if "non challenged" in q or "non-challenged" in q:
        return "abs_non_challenged_incorrect_calls", {"filters": {}}
    if "used challenges" in q or "usage" in q:
        return "abs_challenge_usage", {"filters": {}}
    if "ump" in q or "officiating" in q:
        return "abs_officiating_quality_proxy", {"filters": {}}
    if "location" in q or "high or low" in q or "high/low" in q:
        return "abs_miss_location_analysis", {"filters": {}}
    if "what can you see" in q or "what data" in q or "overview" in q:
        return "abs_dataset_overview", {}
    if "strategy" in q or "recommend" in q:
        return "abs.challenge_strategy", {"filters": {}}
    if "player" in q:
        # naive player extraction
        tail = question.split("player", 1)[-1].strip(" :")
        return "abs.player_report", {"player_name_or_id": tail or question}
    if "week" in q or "summary" in q:
        return "abs.weekly_summary", {"team_name": "All Teams", "week_start": str(date.today())}
    return "abs.run_query", {"question_or_sql": question}


def _find_team_in_question(question: str) -> str | None:
    q = question.lower()
    conn = get_connection()
    try:
        teams = fetch_all_dicts(conn, "SELECT DISTINCT team_name FROM v_team_kpis")
    finally:
        conn.close()
    for row in teams:
        team_name = row["team_name"]
        if (team_name or "").lower() in q:
            return team_name
    return None


def _is_conversational_prompt(question: str) -> bool:
    q = question.strip().lower()
    if not q:
        return True
    small_talk_tokens = {"hi", "hello", "hey", "thanks", "thank you", "test", "just testing", "this is just a test"}
    if q in small_talk_tokens:
        return True
    words = q.split()
    if len(words) <= 5 and any(token in q for token in ["test", "hello", "hey", "thanks"]):
        return True
    return False


@app.post("/chat")
async def chat(req: ChatRequest) -> dict[str, Any]:
    if _is_conversational_prompt(req.question):
        history_payload = [{"role": turn.role, "content": turn.content} for turn in req.history]
        llm_text = await summarize_with_llm_history(
            req.question,
            tool_payload=None,
            history=history_payload,
            analytics_mode=False,
        )
        answer = llm_text or "I can help with ABS strategy, player tendencies, missed-call analysis, and game-by-game challenge usage."
        return {
            "answer": answer,
            "sources": [],
            "recommended_actions": [],
            "supporting_stats": [],
            "tool_used": "conversation",
        }

    tool_name, args = _select_tool(req.question)
    if req.filters and "filters" in args:
        args["filters"] = {**args.get("filters", {}), **req.filters}
    if req.filters.get("team_name") and tool_name == "abs.weekly_summary":
        args["team_name"] = req.filters["team_name"]
    if req.filters.get("week_start") and tool_name == "abs.weekly_summary":
        args["week_start"] = req.filters["week_start"]

    result = call_tool(tool_name, args)
    if result.tool == "abs.player_report" and "No exact player match found." in result.summary:
        team_name = _find_team_in_question(req.question)
        if team_name:
            result = call_tool("abs_challenge_strategy", {"filters": {"team_name": team_name}})

    tool_payload = {
        "tool": result.tool,
        "summary": result.summary,
        "data_preview": result.data[:10],
        "recommended_actions": result.recommended_actions,
    }
    history_payload = [{"role": turn.role, "content": turn.content} for turn in req.history]
    llm_text = await summarize_with_llm_history(req.question, tool_payload, history_payload, analytics_mode=True)
    answer = llm_text or (
        f"Answer: {result.summary}\n\nSupporting Stats: {result.data[:3]}\n\nRecommended Actions: {result.recommended_actions}"
    )

    return {
        "answer": answer,
        "sources": [{"tool": result.tool, "rows": len(result.data)}],
        "recommended_actions": result.recommended_actions,
        "supporting_stats": result.data[:10],
        "tool_used": result.tool,
    }


@app.get("/dashboard/team/{team}")
def dashboard_team(team: str) -> dict[str, Any]:
    conn = get_connection()
    try:
        kpi = fetch_all_dicts(
            conn,
            "SELECT * FROM v_team_kpis WHERE lower(team_name) = lower(?) LIMIT 1",
            (team,),
        )
        high_value_counts = fetch_all_dicts(
            conn,
            """
            SELECT balls, strikes, COUNT(*) AS attempts,
                   ROUND(100.0 * SUM(CASE WHEN challenge_result='overturned' THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0), 2) AS overturn_rate_pct
            FROM v_challenges_enriched
            WHERE lower(challenge_team_name) = lower(?)
            GROUP BY balls, strikes
            ORDER BY attempts DESC
            LIMIT 10
            """,
            (team,),
        )
    finally:
        conn.close()
    if not kpi:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"team": team, "kpis": kpi[0], "high_value_counts": high_value_counts}


@app.get("/dashboard/teams")
def dashboard_teams() -> dict[str, Any]:
    conn = get_connection()
    try:
        teams = fetch_all_dicts(conn, "SELECT DISTINCT team_name FROM v_team_kpis ORDER BY team_name ASC")
    finally:
        conn.close()
    return {"teams": [row["team_name"] for row in teams]}


@app.get("/dashboard/player/{player_id}")
def dashboard_player(player_id: str) -> dict[str, Any]:
    result = player_report(player_id)
    if "No exact player match found." in result.summary:
        raise HTTPException(status_code=404, detail="Player not found")
    return {"player_id": player_id, "summary": result.summary, "payload": result.data, "coaching_notes": result.recommended_actions}


@app.get("/dashboard/players")
def dashboard_players(q: str = "", limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 250))
    conn = get_connection()
    try:
        rows = fetch_all_dicts(
            conn,
            """
            SELECT player_id, player_name, team_name, primary_position
            FROM players
            WHERE lower(player_name) LIKE lower(?) OR lower(player_id) LIKE lower(?)
            ORDER BY player_name ASC
            LIMIT ?
            """,
            (f"%{q}%", f"%{q}%", safe_limit),
        )
    finally:
        conn.close()
    return {"players": rows, "query": q, "limit": safe_limit}


@app.get("/dashboard/positions")
def dashboard_positions(position: str = "", role: str = "", min_challenges: int = 3) -> dict[str, Any]:
    filters: dict[str, Any] = {"min_challenges": min_challenges}
    if position:
        filters["position"] = position
    if role:
        filters["role"] = role
    result = position_accuracy(filters)
    return {"summary": result.summary, "rows": result.data, "recommended_actions": result.recommended_actions}


@app.get("/dashboard/non-challenged")
def dashboard_non_challenged(team_name: str = "") -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if team_name:
        filters["team_name"] = team_name
    result = non_challenged_incorrect_calls(filters)
    return {"summary": result.summary, "rows": result.data, "recommended_actions": result.recommended_actions}


@app.get("/dashboard/challenge-usage")
def dashboard_challenge_usage(team_name: str = "") -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if team_name:
        filters["team_name"] = team_name
    result = challenge_usage(filters)
    return {"summary": result.summary, "rows": result.data, "recommended_actions": result.recommended_actions}


@app.get("/dashboard/officiating-proxy")
def dashboard_officiating_proxy(game_id: str = "") -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if game_id:
        filters["game_id"] = game_id
    result = officiating_quality_proxy(filters)
    return {"summary": result.summary, "rows": result.data, "recommended_actions": result.recommended_actions}


@app.get("/dashboard/miss-locations")
def dashboard_miss_locations(team_name: str = "", role: str = "") -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if team_name:
        filters["team_name"] = team_name
    if role:
        filters["role"] = role
    result = miss_location_analysis(filters)
    return {"summary": result.summary, "rows": result.data, "recommended_actions": result.recommended_actions}


@app.post("/reports/weekly")
def reports_weekly(req: WeeklyReportRequest) -> dict[str, Any]:
    return generate_weekly_report(req.team_name, req.week_start.isoformat())


def _effective_reports_dir() -> Path:
    reports_dir = settings.reports_dir
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        return reports_dir
    except OSError:
        fallback = Path("reports")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


@app.get("/reports/list")
def reports_list() -> dict[str, Any]:
    reports_dir = _effective_reports_dir()
    files = sorted(reports_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "reports": [
            {"name": path.name, "size": path.stat().st_size, "updated_epoch": path.stat().st_mtime}
            for path in files
        ]
    }


@app.get("/reports/content/{report_name}")
def reports_content(report_name: str) -> dict[str, Any]:
    reports_dir = _effective_reports_dir()
    target = (reports_dir / report_name).resolve()
    if target.suffix.lower() != ".md":
        raise HTTPException(status_code=400, detail="Only markdown reports are supported.")
    if reports_dir.resolve() not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid report path.")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Report not found.")
    return {"name": target.name, "markdown": target.read_text(encoding="utf-8")}


@app.get("/", response_class=HTMLResponse)
def web_home() -> str:
    return Path("app/static/index.html").read_text(encoding="utf-8")


@app.get("/team", response_class=HTMLResponse)
def web_team() -> str:
    return Path("app/static/team.html").read_text(encoding="utf-8")


@app.get("/player", response_class=HTMLResponse)
def web_player() -> str:
    return Path("app/static/player.html").read_text(encoding="utf-8")


@app.get("/copilot", response_class=HTMLResponse)
def web_copilot() -> str:
    return Path("app/static/copilot.html").read_text(encoding="utf-8")


@app.get("/reports-view", response_class=HTMLResponse)
def web_reports() -> str:
    return Path("app/static/reports.html").read_text(encoding="utf-8")


# Mount MCP SSE transport for direct agent URL integration.
app.mount("/mcp", mcp.sse_app())
