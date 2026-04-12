from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any

from app.config import settings


def _effective_db_path() -> Path:
    preferred = settings.app_db_path
    try:
        preferred.parent.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        fallback = Path("data/abs_insights.db")
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return fallback


def get_connection() -> sqlite3.Connection:
    db_path = _effective_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if not _schema_ready(conn):
        conn.close()
        initialize_database(base_path=Path("."))
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    return conn


def _schema_ready(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM sqlite_master
        WHERE type='view' AND name='v_team_kpis'
        """
    ).fetchone()
    return bool(row and row[0] >= 1)


def _read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        rows = [row for row in reader]
    return headers, rows


def _create_table_from_csv(
    conn: sqlite3.Connection, table_name: str, csv_path: Path, numeric_cols: set[str]
) -> None:
    headers, rows = _read_csv_rows(csv_path)
    typed_defs = []
    for col in headers:
        col_type = "REAL" if col in numeric_cols else "TEXT"
        typed_defs.append(f'"{col}" {col_type}')

    conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    conn.execute(f'CREATE TABLE "{table_name}" ({", ".join(typed_defs)})')

    placeholders = ", ".join(["?"] * len(headers))
    quoted_columns = ", ".join(f'"{h}"' for h in headers)
    conn.executemany(
        f'INSERT INTO "{table_name}" ({quoted_columns}) VALUES ({placeholders})',
        rows,
    )


def _create_views(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP VIEW IF EXISTS v_challenges_enriched;
        CREATE VIEW v_challenges_enriched AS
        SELECT
            c.challenge_id,
            c.challenger_role,
            c.challenger_player_id,
            c.challenge_team_name,
            c.original_call,
            c.abs_call,
            c.challenge_result,
            p.pitch_id,
            p.game_id,
            p.inning,
            p.inning_half,
            p.outs,
            p.balls,
            p.strikes,
            p.batting_team_name,
            p.fielding_team_name,
            p.batter_id,
            p.pitcher_id,
            p.catcher_id,
            p.called_strike_or_ball,
            p.abs_zone_call,
            p.pitch_x,
            p.pitch_z,
            cp.player_name AS challenger_player_name,
            cp.primary_position AS challenger_position,
            bp.player_name AS batter_name,
            pp.player_name AS pitcher_name,
            ct.player_name AS catcher_name
        FROM abs_challenges c
        LEFT JOIN pitches p ON c.challenge_id = p.challenge_id
        LEFT JOIN players cp ON c.challenger_player_id = cp.player_id
        LEFT JOIN players bp ON p.batter_id = bp.player_id
        LEFT JOIN players pp ON p.pitcher_id = pp.player_id
        LEFT JOIN players ct ON p.catcher_id = ct.player_id;

        DROP VIEW IF EXISTS v_team_kpis;
        CREATE VIEW v_team_kpis AS
        SELECT
            challenge_team_name AS team_name,
            COUNT(*) AS total_challenges,
            SUM(CASE WHEN challenge_result = 'overturned' THEN 1 ELSE 0 END) AS overturned_challenges,
            SUM(CASE WHEN challenge_result = 'confirmed' THEN 1 ELSE 0 END) AS confirmed_challenges,
            ROUND(
                100.0 * SUM(CASE WHEN challenge_result = 'overturned' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
                2
            ) AS overturn_rate_pct,
            SUM(CASE WHEN challenger_role = 'batter' THEN 1 ELSE 0 END) AS batter_challenges,
            SUM(CASE WHEN challenger_role = 'pitcher' THEN 1 ELSE 0 END) AS pitcher_challenges,
            SUM(CASE WHEN challenger_role = 'catcher' THEN 1 ELSE 0 END) AS catcher_challenges,
            SUM(CASE WHEN balls = 3 OR strikes = 2 THEN 1 ELSE 0 END) AS leverage_count_challenges
        FROM v_challenges_enriched
        GROUP BY challenge_team_name;

        DROP VIEW IF EXISTS v_player_kpis;
        CREATE VIEW v_player_kpis AS
        WITH challenged AS (
            SELECT
                challenger_player_id AS player_id,
                COUNT(*) AS total_challenges_made,
                SUM(CASE WHEN challenge_result = 'overturned' THEN 1 ELSE 0 END) AS overturned_when_challenged
            FROM v_challenges_enriched
            GROUP BY challenger_player_id
        ),
        involvement AS (
            SELECT
                p.player_id,
                SUM(CASE WHEN ce.batter_id = p.player_id THEN 1 ELSE 0 END) AS seen_as_batter,
                SUM(CASE WHEN ce.pitcher_id = p.player_id THEN 1 ELSE 0 END) AS seen_as_pitcher,
                SUM(CASE WHEN ce.catcher_id = p.player_id THEN 1 ELSE 0 END) AS seen_as_catcher
            FROM players p
            LEFT JOIN v_challenges_enriched ce ON
                ce.batter_id = p.player_id OR ce.pitcher_id = p.player_id OR ce.catcher_id = p.player_id
            GROUP BY p.player_id
        )
        SELECT
            p.player_id,
            p.player_name,
            p.team_name,
            p.primary_position,
            COALESCE(ch.total_challenges_made, 0) AS total_challenges_made,
            COALESCE(ch.overturned_when_challenged, 0) AS overturned_when_challenged,
            ROUND(
                100.0 * COALESCE(ch.overturned_when_challenged, 0) / NULLIF(COALESCE(ch.total_challenges_made, 0), 0),
                2
            ) AS personal_overturn_rate_pct,
            COALESCE(iv.seen_as_batter, 0) AS seen_as_batter,
            COALESCE(iv.seen_as_pitcher, 0) AS seen_as_pitcher,
            COALESCE(iv.seen_as_catcher, 0) AS seen_as_catcher
        FROM players p
        LEFT JOIN challenged ch ON p.player_id = ch.player_id
        LEFT JOIN involvement iv ON p.player_id = iv.player_id;

        DROP VIEW IF EXISTS v_position_challenge_accuracy;
        CREATE VIEW v_position_challenge_accuracy AS
        SELECT
            COALESCE(challenger_position, 'Unknown') AS primary_position,
            challenger_role,
            COUNT(*) AS total_challenges,
            SUM(CASE WHEN challenge_result = 'overturned' THEN 1 ELSE 0 END) AS correct_challenges,
            SUM(CASE WHEN challenge_result = 'confirmed' THEN 1 ELSE 0 END) AS incorrect_challenges,
            ROUND(
                100.0 * SUM(CASE WHEN challenge_result = 'overturned' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2
            ) AS correct_pct
        FROM v_challenges_enriched
        GROUP BY COALESCE(challenger_position, 'Unknown'), challenger_role
        ORDER BY correct_pct DESC, total_challenges DESC;

        DROP VIEW IF EXISTS v_non_challenged_misses;
        CREATE VIEW v_non_challenged_misses AS
        SELECT
            game_id,
            batting_team_name,
            fielding_team_name,
            pitch_id,
            batter_id,
            pitcher_id,
            catcher_id,
            balls,
            strikes,
            called_strike_or_ball,
            abs_zone_call,
            pitch_x,
            pitch_z,
            CASE
                WHEN pitch_z > sz_top THEN 'high'
                WHEN pitch_z < sz_bot THEN 'low'
                WHEN ABS(pitch_x) > 0.708 THEN 'off-plate'
                ELSE 'in-zone'
            END AS miss_zone_bucket
        FROM pitches
        WHERE lower(COALESCE(was_challenged, '')) NOT IN ('true', '1', 'yes')
          AND lower(COALESCE(called_strike_or_ball, '')) != lower(COALESCE(abs_zone_call, ''));

        DROP VIEW IF EXISTS v_team_game_challenge_usage;
        CREATE VIEW v_team_game_challenge_usage AS
        WITH participants AS (
            SELECT game_id, batting_team_name AS team_name, batter_id AS player_id FROM pitches
            UNION
            SELECT game_id, fielding_team_name AS team_name, pitcher_id AS player_id FROM pitches
            UNION
            SELECT game_id, fielding_team_name AS team_name, catcher_id AS player_id FROM pitches
        )
        SELECT
            ce.game_id,
            ce.challenge_team_name AS team_name,
            COUNT(*) AS total_challenges,
            COUNT(DISTINCT ce.challenger_player_id) AS unique_challengers,
            COUNT(DISTINCT p.player_id) AS unique_players_in_game,
            ROUND(
                100.0 * COUNT(DISTINCT ce.challenger_player_id) / NULLIF(COUNT(DISTINCT p.player_id), 0), 2
            ) AS pct_players_using_challenges
        FROM v_challenges_enriched ce
        LEFT JOIN participants p
            ON p.game_id = ce.game_id
           AND lower(p.team_name) = lower(ce.challenge_team_name)
        GROUP BY ce.game_id, ce.challenge_team_name
        ORDER BY ce.game_id, ce.challenge_team_name;

        DROP VIEW IF EXISTS v_game_call_quality_proxy;
        CREATE VIEW v_game_call_quality_proxy AS
        SELECT
            game_id,
            COUNT(*) AS called_pitches,
            SUM(CASE WHEN lower(COALESCE(called_strike_or_ball, '')) != lower(COALESCE(abs_zone_call, '')) THEN 1 ELSE 0 END) AS missed_calls,
            ROUND(
                100.0 * SUM(CASE WHEN lower(COALESCE(called_strike_or_ball, '')) != lower(COALESCE(abs_zone_call, '')) THEN 1 ELSE 0 END)
                / NULLIF(COUNT(*), 0), 2
            ) AS missed_call_pct
        FROM pitches
        GROUP BY game_id
        ORDER BY missed_call_pct DESC, called_pitches DESC;

        DROP VIEW IF EXISTS v_challenge_miss_locations;
        CREATE VIEW v_challenge_miss_locations AS
        SELECT
            challenge_team_name AS team_name,
            challenger_role,
            CASE
                WHEN pitch_z > 3.21 THEN 'high'
                WHEN pitch_z < 1.62 THEN 'low'
                ELSE 'zone-height'
            END AS vertical_bucket,
            CASE
                WHEN ABS(pitch_x) > 0.708 THEN 'off-plate'
                WHEN ABS(pitch_x) >= 0.55 THEN 'edge'
                ELSE 'middle'
            END AS horizontal_bucket,
            COUNT(*) AS challenges,
            SUM(CASE WHEN challenge_result = 'overturned' THEN 1 ELSE 0 END) AS overturned,
            ROUND(
                100.0 * SUM(CASE WHEN challenge_result = 'overturned' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2
            ) AS overturn_pct
        FROM v_challenges_enriched
        GROUP BY challenge_team_name, challenger_role, vertical_bucket, horizontal_bucket
        ORDER BY overturn_pct DESC, challenges DESC;
        """
    )


def initialize_database(base_path: Path = Path(".")) -> None:
    db_path = _effective_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _create_table_from_csv(
            conn,
            "abs_challenges",
            base_path / "abs_challenges.csv",
            numeric_cols=set(),
        )
        _create_table_from_csv(
            conn,
            "pitches",
            base_path / "pitches.csv",
            numeric_cols={"inning", "outs", "balls", "strikes", "pitch_x", "pitch_z", "sz_top", "sz_bot"},
        )
        _create_table_from_csv(
            conn,
            "players",
            base_path / "players.csv",
            numeric_cols=set(),
        )
        _create_views(conn)
        conn.commit()
    finally:
        conn.close()


def fetch_all_dicts(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]
