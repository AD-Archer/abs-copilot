import csv

from app.database import get_connection, initialize_database


def _count_csv_rows(path: str) -> int:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return sum(1 for _ in csv.reader(f)) - 1


def test_table_row_counts_match_csv() -> None:
    initialize_database()
    conn = get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM abs_challenges").fetchone()[0] == _count_csv_rows("abs_challenges.csv")
        assert conn.execute("SELECT COUNT(*) FROM pitches").fetchone()[0] == _count_csv_rows("pitches.csv")
        assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == _count_csv_rows("players.csv")
    finally:
        conn.close()


def test_challenge_totals_match_confirmed_plus_overturned() -> None:
    initialize_database()
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM abs_challenges").fetchone()[0]
        split_total = conn.execute(
            """
            SELECT
                SUM(CASE WHEN challenge_result='confirmed' THEN 1 ELSE 0 END) +
                SUM(CASE WHEN challenge_result='overturned' THEN 1 ELSE 0 END)
            FROM abs_challenges
            """
        ).fetchone()[0]
        assert total == split_total
    finally:
        conn.close()

