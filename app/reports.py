from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.analytics import weekly_summary
from app.config import settings


def render_weekly_markdown(team_name: str, week_start: str, payload: dict[str, Any]) -> str:
    lines = [
        f"# ABS Weekly Summary: {team_name}",
        "",
        f"- Week start: {week_start}",
        f"- Generated at: {datetime.now(UTC).isoformat()}",
        "",
        "## What Changed",
        payload.get("summary", "Summary unavailable."),
        "",
        "## Supporting KPIs",
    ]
    for row in payload.get("data", [])[:10]:
        lines.append(f"- {row}")
    lines.extend(
        [
            "",
            "## Suggested Focus Areas",
        ]
    )
    for action in payload.get("recommended_actions", []):
        lines.append(f"- {action}")
    return "\n".join(lines)


def generate_weekly_report(team_name: str, week_start: str) -> dict[str, Any]:
    result = weekly_summary(team_name=team_name, week_start=week_start)
    payload = {
        "tool": result.tool,
        "summary": result.summary,
        "data": result.data,
        "recommended_actions": result.recommended_actions,
    }
    md = render_weekly_markdown(team_name, week_start, payload)

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
    html_path.write_text(
        "<html><body><pre>" + md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + "</pre></body></html>",
        encoding="utf-8",
    )

    return {
        "team_name": team_name,
        "week_start": week_start,
        "summary": payload["summary"],
        "report_markdown_path": str(Path(md_path)),
        "report_html_path": str(Path(html_path)),
        "recommended_actions": payload["recommended_actions"],
    }
