from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from app.analytics import (
    challenge_strategy,
    challenge_usage,
    miss_location_analysis,
    non_challenged_incorrect_calls,
    officiating_quality_proxy,
    player_report,
    position_accuracy,
    run_query,
    weekly_summary,
)


mcp = FastMCP("ABS Insight Copilot")


def _pack(tool_result: Any) -> dict[str, Any]:
    return {
        "tool": tool_result.tool,
        "summary": tool_result.summary,
        "data": tool_result.data,
        "recommended_actions": tool_result.recommended_actions,
    }


@mcp.tool(name="abs_run_query", description="Safe read-only analytics over ABS views.")
def mcp_run_query(question_or_sql: str) -> dict[str, Any]:
    return _pack(run_query(question_or_sql))


@mcp.tool(
    name="abs_challenge_strategy",
    description="Actionable recommendations by team/count/role challenge patterns.",
)
def mcp_challenge_strategy(filters: dict[str, Any] | None = None) -> dict[str, Any]:
    return _pack(challenge_strategy(filters or {}))


@mcp.tool(
    name="abs_player_report",
    description="Individual challenge tendencies and coaching notes for a player.",
)
def mcp_player_report(player_name_or_id: str) -> dict[str, Any]:
    return _pack(player_report(player_name_or_id))


@mcp.tool(
    name="abs_weekly_summary",
    description="Weekly narrative payload for team review and action planning.",
)
def mcp_weekly_summary(team_name: str, week_start: str) -> dict[str, Any]:
    return _pack(weekly_summary(team_name, week_start))


@mcp.tool(
    name="abs_position_accuracy",
    description="Correct/incorrect challenge percentages split by primary position and role.",
)
def mcp_position_accuracy(filters: dict[str, Any] | None = None) -> dict[str, Any]:
    return _pack(position_accuracy(filters or {}))


@mcp.tool(
    name="abs_non_challenged_incorrect_calls",
    description="Analyze incorrect calls that were not challenged.",
)
def mcp_non_challenged_incorrect_calls(filters: dict[str, Any] | None = None) -> dict[str, Any]:
    return _pack(non_challenged_incorrect_calls(filters or {}))


@mcp.tool(
    name="abs_challenge_usage",
    description="How many challenges were used per game and challenger participation rates.",
)
def mcp_challenge_usage(filters: dict[str, Any] | None = None) -> dict[str, Any]:
    return _pack(challenge_usage(filters or {}))


@mcp.tool(
    name="abs_officiating_quality_proxy",
    description="Game-level call quality proxy from called-vs-ABS disagreement rates.",
)
def mcp_officiating_quality_proxy(filters: dict[str, Any] | None = None) -> dict[str, Any]:
    return _pack(officiating_quality_proxy(filters or {}))


@mcp.tool(
    name="abs_miss_location_analysis",
    description="Where challenged pitches are most often missed (high/low/edge/off-plate).",
)
def mcp_miss_location_analysis(filters: dict[str, Any] | None = None) -> dict[str, Any]:
    return _pack(miss_location_analysis(filters or {}))
