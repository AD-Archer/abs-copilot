from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.database import fetch_all_dicts, get_connection
from app.sql_guard import ensure_safe_read_only_sql


@dataclass
class ToolResult:
    tool: str
    summary: str
    data: list[dict[str, Any]]
    recommended_actions: list[str]


def _sql_from_question(question: str) -> str:
    q = question.lower()
    team_match = re.search(r"team\s+([a-z0-9 .'-]+)", q)
    if "team" in q and "overturn" in q:
        if team_match:
            team_name = team_match.group(1).strip().title()
            return f"""
                SELECT * FROM v_team_kpis
                WHERE lower(team_name) = lower('{team_name}')
                LIMIT {settings.result_row_limit}
            """
        return f"SELECT * FROM v_team_kpis ORDER BY overturn_rate_pct DESC LIMIT {settings.result_row_limit}"
    if "player" in q:
        return f"SELECT * FROM v_player_kpis ORDER BY total_challenges_made DESC LIMIT {settings.result_row_limit}"
    return f"SELECT * FROM v_challenges_enriched LIMIT {settings.result_row_limit}"


def run_query(question_or_sql: str) -> ToolResult:
    sql = question_or_sql.strip()
    if re.search(r"\b(insert|update|delete|drop|alter|create|replace|truncate|pragma|vacuum)\b", sql, re.IGNORECASE):
        raise ValueError("Only read-only analytics are allowed.")
    if not re.match(r"^\s*(select|with)\b", sql, re.IGNORECASE):
        sql = _sql_from_question(question_or_sql)
    ensure_safe_read_only_sql(sql)

    conn = get_connection()
    try:
        rows = fetch_all_dicts(conn, sql)
        return ToolResult(
            tool="abs.run_query",
            summary=f"Returned {len(rows)} row(s).",
            data=rows[: settings.result_row_limit],
            recommended_actions=["Drill into a team or player-level question for actionable coaching recommendations."],
        )
    finally:
        conn.close()


def challenge_strategy(filters: dict[str, Any] | None = None) -> ToolResult:
    filters = filters or {}
    team = filters.get("team_name")
    role = filters.get("role")
    balls = filters.get("balls")
    strikes = filters.get("strikes")

    where = []
    params: list[Any] = []
    if team:
        where.append("lower(challenge_team_name) = lower(?)")
        params.append(team)
    if role:
        where.append("lower(challenger_role) = lower(?)")
        params.append(role)
    if balls is not None:
        where.append("balls = ?")
        params.append(balls)
    if strikes is not None:
        where.append("strikes = ?")
        params.append(strikes)

    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT
            challenge_team_name AS team_name,
            challenger_role,
            balls,
            strikes,
            COUNT(*) AS opportunities,
            SUM(CASE WHEN challenge_result = 'overturned' THEN 1 ELSE 0 END) AS overturned,
            ROUND(
                100.0 * SUM(CASE WHEN challenge_result = 'overturned' THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0), 2
            ) AS overturn_rate_pct
        FROM v_challenges_enriched
        {where_clause}
        GROUP BY challenge_team_name, challenger_role, balls, strikes
        HAVING opportunities >= 3
        ORDER BY overturn_rate_pct DESC, opportunities DESC
        LIMIT ?
    """
    params.append(settings.result_row_limit)

    conn = get_connection()
    try:
        rows = fetch_all_dicts(conn, sql, tuple(params))
    finally:
        conn.close()

    actions: list[str] = []
    for row in rows[:3]:
        actions.append(
            f"{row['team_name']} {row['challenger_role']} in {int(row['balls'])}-{int(row['strikes'])} counts shows {row['overturn_rate_pct']}% overturn rate over {row['opportunities']} attempts."
        )
    if not actions:
        actions = ["No strong split found with current filters. Widen filters to find stable challenge patterns."]
    return ToolResult(
        tool="abs.challenge_strategy",
        summary="Computed challenge strategy opportunities by team/count/role.",
        data=rows,
        recommended_actions=actions,
    )


def player_report(player_name_or_id: str) -> ToolResult:
    conn = get_connection()
    try:
        player_rows = fetch_all_dicts(
            conn,
            """
            SELECT * FROM v_player_kpis
            WHERE lower(player_id) = lower(?) OR lower(player_name) = lower(?)
            LIMIT 1
            """,
            (player_name_or_id, player_name_or_id),
        )
        if not player_rows:
            candidates = fetch_all_dicts(
                conn,
                """
                SELECT * FROM v_player_kpis
                WHERE lower(player_name) LIKE lower(?)
                ORDER BY total_challenges_made DESC
                LIMIT 5
                """,
                (f"%{player_name_or_id}%",),
            )
            return ToolResult(
                tool="abs.player_report",
                summary="No exact player match found.",
                data=candidates,
                recommended_actions=["Use exact player_id or full player_name for a detailed report."],
            )

        player = player_rows[0]
        role_splits = fetch_all_dicts(
            conn,
            """
            SELECT challenger_role,
                   COUNT(*) AS attempts,
                   SUM(CASE WHEN challenge_result = 'overturned' THEN 1 ELSE 0 END) AS overturned,
                   ROUND(100.0 * SUM(CASE WHEN challenge_result = 'overturned' THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0), 2) AS overturn_rate_pct
            FROM v_challenges_enriched
            WHERE challenger_player_id = ?
            GROUP BY challenger_role
            ORDER BY attempts DESC
            """,
            (player["player_id"],),
        )
    finally:
        conn.close()

    notes = [
        f"{player['player_name']} has {player['total_challenges_made']} total challenges with {player['personal_overturn_rate_pct']}% success.",
        f"Usage context: batter={player['seen_as_batter']}, pitcher={player['seen_as_pitcher']}, catcher={player['seen_as_catcher']}.",
    ]
    if role_splits:
        top_role = role_splits[0]
        notes.append(
            f"Most active challenge role is {top_role['challenger_role']} ({top_role['attempts']} attempts, {top_role['overturn_rate_pct']}% overturned)."
        )

    return ToolResult(
        tool="abs.player_report",
        summary=f"Generated player tendencies report for {player['player_name']}.",
        data=[player, *role_splits],
        recommended_actions=notes,
    )


def weekly_summary(team_name: str, week_start: str) -> ToolResult:
    conn = get_connection()
    try:
        team_rows = fetch_all_dicts(
            conn,
            """
            SELECT * FROM v_team_kpis
            WHERE lower(team_name) = lower(?)
            LIMIT 1
            """,
            (team_name,),
        )
        top_counts = fetch_all_dicts(
            conn,
            """
            SELECT balls, strikes,
                   COUNT(*) AS attempts,
                   ROUND(100.0 * SUM(CASE WHEN challenge_result = 'overturned' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS overturn_rate_pct
            FROM v_challenges_enriched
            WHERE lower(challenge_team_name) = lower(?)
            GROUP BY balls, strikes
            HAVING attempts >= 3
            ORDER BY overturn_rate_pct DESC, attempts DESC
            LIMIT 5
            """,
            (team_name,),
        )
    finally:
        conn.close()

    if not team_rows:
        return ToolResult(
            tool="abs.weekly_summary",
            summary="No matching team found for weekly summary.",
            data=[],
            recommended_actions=["Check team name spelling against available records."],
        )

    team_kpi = team_rows[0]
    actions = [
        f"Week of {week_start}: {team_name} posted {team_kpi['overturn_rate_pct']}% overturn rate ({team_kpi['overturned_challenges']}/{team_kpi['total_challenges']} challenges).",
        "Prioritize challenge spots where called-vs-ABS mismatch has historically produced higher overturn rates.",
    ]
    if top_counts:
        best = top_counts[0]
        actions.append(
            f"Best leverage count this week model: {int(best['balls'])}-{int(best['strikes'])} ({best['overturn_rate_pct']}% over {best['attempts']} attempts)."
        )

    return ToolResult(
        tool="abs.weekly_summary",
        summary="Built weekly narrative payload for team coaching review.",
        data=[team_kpi, *top_counts],
        recommended_actions=actions,
    )


def position_accuracy(filters: dict[str, Any] | None = None) -> ToolResult:
    filters = filters or {}
    position = filters.get("position")
    role = filters.get("role")
    min_challenges = int(filters.get("min_challenges", 3))
    where = ["total_challenges >= ?"]
    params: list[Any] = [min_challenges]
    if position:
        where.append("lower(primary_position) = lower(?)")
        params.append(position)
    if role:
        where.append("lower(challenger_role) = lower(?)")
        params.append(role)
    sql = f"""
        SELECT * FROM v_position_challenge_accuracy
        WHERE {' AND '.join(where)}
        ORDER BY correct_pct DESC, total_challenges DESC
        LIMIT ?
    """
    params.append(settings.result_row_limit)
    conn = get_connection()
    try:
        rows = fetch_all_dicts(conn, sql, tuple(params))
    finally:
        conn.close()
    actions = []
    for row in rows[:3]:
        actions.append(
            f"{row['primary_position']} ({row['challenger_role']}) shows {row['correct_pct']}% correct challenge rate across {row['total_challenges']} challenges."
        )
    if not actions:
        actions = ["No qualifying position split found. Try lowering min_challenges or removing filters."]
    return ToolResult(
        tool="abs_position_accuracy",
        summary="Position-based challenge accuracy (correct vs incorrect) computed.",
        data=rows,
        recommended_actions=actions,
    )


def non_challenged_incorrect_calls(filters: dict[str, Any] | None = None) -> ToolResult:
    filters = filters or {}
    team_name = filters.get("team_name")
    sql = """
        SELECT
            COALESCE(batting_team_name, fielding_team_name) AS team_hint,
            miss_zone_bucket,
            COUNT(*) AS missed_calls
        FROM v_non_challenged_misses
    """
    params: list[Any] = []
    if team_name:
        sql += """
            WHERE lower(batting_team_name) = lower(?)
               OR lower(fielding_team_name) = lower(?)
        """
        params.extend([team_name, team_name])
    sql += """
        GROUP BY team_hint, miss_zone_bucket
        ORDER BY missed_calls DESC
        LIMIT ?
    """
    params.append(settings.result_row_limit)
    conn = get_connection()
    try:
        rows = fetch_all_dicts(conn, sql, tuple(params))
    finally:
        conn.close()
    total = sum(int(r["missed_calls"]) for r in rows)
    actions = [
        f"Identified {total} non-challenged missed calls in the selected scope.",
        "Review high-volume miss buckets and train bench/catcher on challenge triggers in those zones.",
    ]
    return ToolResult(
        tool="abs_non_challenged_incorrect_calls",
        summary="Computed non-challenged incorrect call distribution.",
        data=rows,
        recommended_actions=actions,
    )


def challenge_usage(filters: dict[str, Any] | None = None) -> ToolResult:
    filters = filters or {}
    team_name = filters.get("team_name")
    cap = int(filters.get("challenge_cap_per_team_game", settings.challenge_cap_per_team_game))
    sql = "SELECT * FROM v_team_game_challenge_usage"
    params: list[Any] = []
    if team_name:
        sql += " WHERE lower(team_name) = lower(?)"
        params.append(team_name)
    sql += " ORDER BY total_challenges DESC, unique_challengers DESC LIMIT ?"
    params.append(settings.result_row_limit)
    conn = get_connection()
    try:
        rows = fetch_all_dicts(conn, sql, tuple(params))
    finally:
        conn.close()
    for row in rows:
        used_pct = round(100.0 * float(row["total_challenges"]) / max(cap, 1), 2)
        row["challenge_cap_assumed"] = cap
        row["pct_cap_used"] = used_pct
    actions = []
    for row in rows[:3]:
        actions.append(
            f"Game {row['game_id']} {row['team_name']}: {row['total_challenges']} challenges used ({row['pct_cap_used']}% of assumed cap {cap}), {row['unique_challengers']} unique challengers."
        )
    if not actions:
        actions = ["No usage rows found for current filters."]
    return ToolResult(
        tool="abs_challenge_usage",
        summary="Challenge usage per game and challenger participation computed.",
        data=rows,
        recommended_actions=actions,
    )


def miss_location_analysis(filters: dict[str, Any] | None = None) -> ToolResult:
    filters = filters or {}
    team_name = filters.get("team_name")
    role = filters.get("role")
    where = []
    params: list[Any] = []
    if team_name:
        where.append("lower(team_name) = lower(?)")
        params.append(team_name)
    if role:
        where.append("lower(challenger_role) = lower(?)")
        params.append(role)
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT * FROM v_challenge_miss_locations
        {where_clause}
        ORDER BY overturn_pct DESC, challenges DESC
        LIMIT ?
    """
    params.append(settings.result_row_limit)
    conn = get_connection()
    try:
        rows = fetch_all_dicts(conn, sql, tuple(params))
    finally:
        conn.close()
    actions = []
    for row in rows[:3]:
        actions.append(
            f"{row['team_name']} {row['challenger_role']} gets {row['overturn_pct']}% overturns on {row['vertical_bucket']}/{row['horizontal_bucket']} pitches ({row['challenges']} challenges)."
        )
    if not actions:
        actions = ["No location pattern found for current filters."]
    return ToolResult(
        tool="abs_miss_location_analysis",
        summary="Challenge miss-location analysis (high/low/edge/off-plate) computed.",
        data=rows,
        recommended_actions=actions,
    )


def officiating_quality_proxy(filters: dict[str, Any] | None = None) -> ToolResult:
    filters = filters or {}
    game_id = filters.get("game_id")
    sql = "SELECT * FROM v_game_call_quality_proxy"
    params: list[Any] = []
    if game_id:
        sql += " WHERE game_id = ?"
        params.append(game_id)
    sql += " ORDER BY missed_call_pct DESC, called_pitches DESC LIMIT ?"
    params.append(settings.result_row_limit)
    conn = get_connection()
    try:
        rows = fetch_all_dicts(conn, sql, tuple(params))
    finally:
        conn.close()
    actions = [
        "This is a game-level proxy for call quality (no umpire IDs available in source data).",
        "Use high missed_call_pct games as review targets for challenge readiness planning.",
    ]
    return ToolResult(
        tool="abs_officiating_quality_proxy",
        summary="Computed game-level called-vs-ABS disagreement rate.",
        data=rows,
        recommended_actions=actions,
    )
