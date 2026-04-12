from __future__ import annotations

from typing import Any, Callable

from app import analytics


ToolFn = Callable[..., analytics.ToolResult]

TOOLS: dict[str, ToolFn] = {
    "abs.run_query": analytics.run_query,
    "abs_run_query": analytics.run_query,
    "abs.challenge_strategy": analytics.challenge_strategy,
    "abs_challenge_strategy": analytics.challenge_strategy,
    "abs.player_report": analytics.player_report,
    "abs_player_report": analytics.player_report,
    "abs.weekly_summary": analytics.weekly_summary,
    "abs_weekly_summary": analytics.weekly_summary,
    "abs_position_accuracy": analytics.position_accuracy,
    "abs_non_challenged_incorrect_calls": analytics.non_challenged_incorrect_calls,
    "abs_challenge_usage": analytics.challenge_usage,
    "abs_miss_location_analysis": analytics.miss_location_analysis,
    "abs_officiating_quality_proxy": analytics.officiating_quality_proxy,
}


def list_tools() -> list[dict[str, Any]]:
    return [
        {"name": "abs_run_query", "description": "Run read-only analytics SQL or natural-language lookup."},
        {"name": "abs_challenge_strategy", "description": "Recommend challenge strategies by team/count/role."},
        {"name": "abs_player_report", "description": "Return player challenge tendencies and coaching notes."},
        {"name": "abs_weekly_summary", "description": "Build a weekly team summary payload with suggested focus areas."},
        {"name": "abs_position_accuracy", "description": "Correct/incorrect challenge rates by player position and role."},
        {"name": "abs_non_challenged_incorrect_calls", "description": "Missed calls that were not challenged."},
        {"name": "abs_challenge_usage", "description": "Challenge usage and participation per game."},
        {"name": "abs_miss_location_analysis", "description": "Challenge results by high/low and horizontal location buckets."},
        {"name": "abs_officiating_quality_proxy", "description": "Game-level called-vs-ABS disagreement proxy."},
    ]


def call_tool(name: str, arguments: dict[str, Any]) -> analytics.ToolResult:
    tool = TOOLS.get(name)
    if not tool:
        raise ValueError(f"Unknown tool: {name}")

    if name in {"abs.run_query", "abs_run_query"}:
        return tool(arguments.get("question_or_sql", ""))
    if name in {"abs.challenge_strategy", "abs_challenge_strategy"}:
        return tool(arguments.get("filters", {}))
    if name in {"abs.player_report", "abs_player_report"}:
        return tool(arguments.get("player_name_or_id", ""))
    if name in {"abs.weekly_summary", "abs_weekly_summary"}:
        return tool(arguments.get("team_name", ""), arguments.get("week_start", ""))
    if name == "abs_position_accuracy":
        return tool(arguments.get("filters", {}))
    if name == "abs_non_challenged_incorrect_calls":
        return tool(arguments.get("filters", {}))
    if name == "abs_challenge_usage":
        return tool(arguments.get("filters", {}))
    if name == "abs_miss_location_analysis":
        return tool(arguments.get("filters", {}))
    if name == "abs_officiating_quality_proxy":
        return tool(arguments.get("filters", {}))
    raise ValueError(f"Unhandled tool call: {name}")
