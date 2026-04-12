from __future__ import annotations

import re

READ_ONLY_PATTERN = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE | re.DOTALL)
FORBIDDEN_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|VACUUM|TRUNCATE)\b",
    re.IGNORECASE,
)


def ensure_safe_read_only_sql(sql: str) -> None:
    if not sql or not READ_ONLY_PATTERN.search(sql):
        raise ValueError("Only read-only SELECT/WITH queries are allowed.")
    if FORBIDDEN_PATTERN.search(sql):
        raise ValueError("Forbidden keyword found in query.")

