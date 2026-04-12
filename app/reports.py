from __future__ import annotations

from datetime import UTC, datetime
import html
from pathlib import Path
from typing import Any

from app.analytics import (
    challenge_usage,
    miss_location_analysis,
    non_challenged_incorrect_calls,
    weekly_summary,
)
from app.config import settings
from app.database import fetch_all_dicts, get_connection


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def _build_report_context(team_name: str, week_start: str) -> dict[str, Any]:
    weekly = weekly_summary(team_name=team_name, week_start=week_start)
    usage = challenge_usage({"team_name": team_name})
    locations = miss_location_analysis({"team_name": team_name})
    non_chall = non_challenged_incorrect_calls({"team_name": team_name})

    conn = get_connection()
    try:
        team_kpi_rows = fetch_all_dicts(
            conn,
            "SELECT * FROM v_team_kpis WHERE lower(team_name)=lower(?) LIMIT 1",
            (team_name,),
        )
        league_rows = fetch_all_dicts(
            conn,
            """
            SELECT
              ROUND(AVG(overturn_rate_pct),2) AS league_avg_overturn_pct,
              COUNT(*) AS teams
            FROM v_team_kpis
            """,
        )
        rank_rows = fetch_all_dicts(
            conn,
            """
            SELECT team_name, overturn_rate_pct
            FROM v_team_kpis
            ORDER BY overturn_rate_pct DESC
            """,
        )
    finally:
        conn.close()

    team_kpi = team_kpi_rows[0] if team_kpi_rows else {}
    league = league_rows[0] if league_rows else {"league_avg_overturn_pct": 0, "teams": 0}
    rank = next((idx + 1 for idx, row in enumerate(rank_rows) if (row["team_name"] or "").lower() == team_name.lower()), None)

    return {
        "weekly": weekly,
        "usage": usage,
        "locations": locations,
        "non_chall": non_chall,
        "team_kpi": team_kpi,
        "league": league,
        "rank": rank,
    }


def render_weekly_markdown(team_name: str, week_start: str, context: dict[str, Any]) -> str:
    weekly = context["weekly"]
    usage = context["usage"]
    locations = context["locations"]
    non_chall = context["non_chall"]
    team_kpi = context["team_kpi"]
    league = context["league"]
    rank = context["rank"]

    team_overturn = _safe_number(team_kpi.get("overturn_rate_pct"))
    league_overturn = _safe_number(league.get("league_avg_overturn_pct"))
    delta_vs_league = round(team_overturn - league_overturn, 2)

    top_counts = weekly.data[1:6] if weekly.data else []
    top_usage = usage.data[:5]
    top_locations = locations.data[:5]
    non_chall_top = non_chall.data[:5]

    lines = [
        f"# ABS Weekly Coaching Report: {team_name}",
        "",
        f"- Week start: {week_start}",
        f"- Generated at: {datetime.now(UTC).isoformat()}",
        f"- Team overturn rate: {team_overturn:.2f}%",
        f"- League avg overturn rate: {league_overturn:.2f}%",
        f"- Delta vs league: {delta_vs_league:+.2f}%",
        f"- League rank: {rank if rank is not None else 'N/A'} of {int(_safe_number(league.get('teams')))}",
        "",
        "## Executive Summary",
        weekly.summary or "Summary unavailable.",
        "",
        "## Coaching Narrative",
    ]
    for action in weekly.recommended_actions[:3]:
        lines.append(f"- {action}")

    lines.extend(
        [
            "",
            "## Team KPI Snapshot",
            _markdown_table(
                ["Metric", "Value"],
                [
                    ["Total Challenges", team_kpi.get("total_challenges", "N/A")],
                    ["Overturned", team_kpi.get("overturned_challenges", "N/A")],
                    ["Confirmed", team_kpi.get("confirmed_challenges", "N/A")],
                    ["Overturn Rate %", team_kpi.get("overturn_rate_pct", "N/A")],
                    ["Batter Challenges", team_kpi.get("batter_challenges", "N/A")],
                    ["Pitcher Challenges", team_kpi.get("pitcher_challenges", "N/A")],
                    ["Catcher Challenges", team_kpi.get("catcher_challenges", "N/A")],
                ],
            ),
            "",
            "## High-Value Count Opportunities",
        ]
    )

    if top_counts:
        lines.append(
            _markdown_table(
                ["Count", "Attempts", "Overturn %"],
                [
                    [f"{int(_safe_number(r['balls']))}-{int(_safe_number(r['strikes']))}", r.get("attempts", 0), r.get("overturn_rate_pct", 0)]
                    for r in top_counts
                ],
            )
        )
    else:
        lines.append("- No qualifying high-value count opportunities were found.")

    lines.extend(
        [
            "",
            "## Challenge Usage And Participation",
        ]
    )
    if top_usage:
        lines.append(
            _markdown_table(
                ["Game", "Challenges Used", "% Cap Used", "Unique Challengers", "% Players Challenging"],
                [
                    [
                        r.get("game_id", "N/A"),
                        r.get("total_challenges", 0),
                        r.get("pct_cap_used", 0),
                        r.get("unique_challengers", 0),
                        r.get("pct_players_using_challenges", 0),
                    ]
                    for r in top_usage
                ],
            )
        )
    else:
        lines.append("- No challenge usage rows were found for this team.")

    lines.extend(
        [
            "",
            "## Miss Location Profile (Challenged Pitches)",
        ]
    )
    if top_locations:
        lines.append(
            _markdown_table(
                ["Role", "Vertical", "Horizontal", "Challenges", "Overturn %"],
                [
                    [
                        r.get("challenger_role", "N/A"),
                        r.get("vertical_bucket", "N/A"),
                        r.get("horizontal_bucket", "N/A"),
                        r.get("challenges", 0),
                        r.get("overturn_pct", 0),
                    ]
                    for r in top_locations
                ],
            )
        )
    else:
        lines.append("- No location profile rows were found for this team.")

    lines.extend(
        [
            "",
            "## Non-Challenged Incorrect Calls (Risk Flags)",
        ]
    )
    if non_chall_top:
        lines.append(
            _markdown_table(
                ["Team Context", "Miss Zone Bucket", "Missed Calls"],
                [[r.get("team_hint", "N/A"), r.get("miss_zone_bucket", "N/A"), r.get("missed_calls", 0)] for r in non_chall_top],
            )
        )
    else:
        lines.append("- No non-challenged incorrect call rows in current scope.")

    lines.extend(
        [
            "",
            "## Recommended Focus Areas",
        ]
    )
    for action in weekly.recommended_actions:
        lines.append(f"- {action}")

    lines.extend(
        [
            "- Prioritize review sessions for pitch-location buckets with high missed-call volume and low challenge conversion.",
            "- Reinforce role-specific challenge triggers in counts with sustained overturn edge.",
            "",
            "## Next Week Plan",
            "1. Review top two miss-location buckets in bullpen/catcher prep.",
            "2. Define challenge trigger rules for 2-3 leverage counts per role.",
            "3. Track usage discipline against challenge cap per game.",
        ]
    )
    return "\n".join(lines)


def _render_weekly_html(report_title: str, markdown_text: str) -> str:
    escaped = html.escape(markdown_text)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(report_title)}</title>
  <style>
    body {{ font-family: Inter, Segoe UI, Arial, sans-serif; margin: 0; background: #f6f8fb; color: #12243d; }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 24px; }}
    .card {{ background: #fff; border-radius: 12px; padding: 16px; box-shadow: 0 8px 20px rgba(0,0,0,.06); }}
    h1 {{ margin-top: 0; }}
    pre {{ white-space: pre-wrap; line-height: 1.45; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>{html.escape(report_title)}</h1>
      <pre>{escaped}</pre>
    </div>
  </div>
</body>
</html>"""


def generate_weekly_report(team_name: str, week_start: str) -> dict[str, Any]:
    context = _build_report_context(team_name=team_name, week_start=week_start)
    md = render_weekly_markdown(team_name, week_start, context)

    report_title = f"ABS Weekly Coaching Report - {team_name} ({week_start})"
    html_body = _render_weekly_html(report_title, md)

    reports_dir = settings.reports_dir
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        reports_dir = Path("reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
    slug = team_name.lower().replace(" ", "_")
    stem = f"{slug}_{week_start}"
    md_path = reports_dir / f"{stem}.md"
    html_path = reports_dir / f"{stem}.html"
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(html_body, encoding="utf-8")

    weekly = context["weekly"]
    return {
        "team_name": team_name,
        "week_start": week_start,
        "summary": weekly.summary,
        "report_markdown_path": str(Path(md_path)),
        "report_html_path": str(Path(html_path)),
        "recommended_actions": weekly.recommended_actions,
        "report_sections": [
            "Executive Summary",
            "Coaching Narrative",
            "Team KPI Snapshot",
            "High-Value Count Opportunities",
            "Challenge Usage And Participation",
            "Miss Location Profile (Challenged Pitches)",
            "Non-Challenged Incorrect Calls (Risk Flags)",
            "Recommended Focus Areas",
            "Next Week Plan",
        ],
    }
