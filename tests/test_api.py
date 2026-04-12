from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_mcp_legacy_aliases() -> None:
    sse = client.get("/sse", follow_redirects=False)
    assert sse.status_code == 307
    assert sse.headers["location"] == "/mcp/sse"

    msgs = client.post("/messages", follow_redirects=False)
    assert msgs.status_code == 307
    assert msgs.headers["location"] == "/mcp/messages"


def test_mcp_tool_list() -> None:
    response = client.get("/api/mcp/tools")
    assert response.status_code == 200
    tools = response.json()["tools"]
    names = {t["name"] for t in tools}
    assert "abs_run_query" in names
    assert "abs_challenge_strategy" in names
    assert "abs_player_report" in names
    assert "abs_weekly_summary" in names
    assert "abs_position_accuracy" in names
    assert "abs_non_challenged_incorrect_calls" in names
    assert "abs_challenge_usage" in names
    assert "abs_officiating_quality_proxy" in names
    assert "abs_miss_location_analysis" in names
    assert "abs_dataset_overview" in names


def test_read_only_enforced() -> None:
    response = client.post(
        "/api/mcp/call",
        json={
            "tool": "abs.run_query",
            "arguments": {"question_or_sql": "DROP TABLE pitches;"},
        },
    )
    assert response.status_code == 400
    assert "read-only" in response.json()["detail"].lower() or "forbidden" in response.json()["detail"].lower()


def test_chat_uses_tool_path() -> None:
    response = client.post("/chat", json={"question": "What are team overturn rates?", "filters": {}})
    assert response.status_code == 200
    body = response.json()
    assert "tool_used" in body
    assert body["tool_used"] in {
        "abs.run_query",
        "abs.challenge_strategy",
        "abs.player_report",
        "abs.weekly_summary",
        "abs_position_accuracy",
        "abs_non_challenged_incorrect_calls",
        "abs_challenge_usage",
        "abs_officiating_quality_proxy",
        "abs_miss_location_analysis",
        "abs_dataset_overview",
    }
    assert "recommended_actions" in body


def test_chat_conversational_mode() -> None:
    response = client.post("/chat", json={"question": "this is just a test", "filters": {}, "history": []})
    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] == "conversation"


def test_chat_team_name_routes_to_team_tool() -> None:
    response = client.post(
        "/chat",
        json={"question": "What is Austin Aces challenge success rate?", "filters": {}, "history": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] in {"abs.challenge_strategy", "abs_challenge_strategy", "abs.run_query"}


def test_dashboard_team_contract() -> None:
    response = client.get("/dashboard/team/Seattle Mariners")
    # Dataset has only four teams and may not include this team; check contract via fallback.
    if response.status_code == 404:
        response = client.post(
            "/api/mcp/call",
            json={"tool": "abs.run_query", "arguments": {"question_or_sql": "SELECT DISTINCT team_name FROM v_team_kpis LIMIT 1"}},
        )
        team = response.json()["data"][0]["team_name"]
        response = client.get(f"/dashboard/team/{team}")
    assert response.status_code == 200
    body = response.json()
    assert "kpis" in body
    assert "high_value_counts" in body


def test_weekly_report_generation() -> None:
    seed = client.post(
        "/api/mcp/call",
        json={"tool": "abs.run_query", "arguments": {"question_or_sql": "SELECT team_name FROM v_team_kpis LIMIT 1"}},
    )
    team_name = seed.json()["data"][0]["team_name"]
    response = client.post("/reports/weekly", json={"team_name": team_name, "week_start": "2026-01-05"})
    assert response.status_code == 200
    body = response.json()
    assert body["team_name"] == team_name
    assert body["report_markdown_path"].endswith(".md")
    assert body["report_html_path"].endswith(".html")
    assert "report_sections" in body
    assert "Executive Summary" in body["report_sections"]

    with open(body["report_markdown_path"], "r", encoding="utf-8") as f:
        md = f.read()
    assert "## Executive Summary" in md
    assert "## Team KPI Snapshot" in md
    assert "## High-Value Count Opportunities" in md
    assert "## Next Week Plan" in md
