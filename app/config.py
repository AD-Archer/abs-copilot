from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_db_path: Path = Path(os.getenv("APP_DB_PATH", "data/abs_insights.db"))
    result_row_limit: int = int(os.getenv("RESULT_ROW_LIMIT", "200"))
    llm_base_url: str | None = os.getenv("LLM_BASE_URL") or None
    llm_api_key: str | None = os.getenv("LLM_API_KEY") or None
    llm_model: str | None = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite-preview") or None
    reports_dir: Path = Path(os.getenv("REPORTS_DIR", "reports"))
    challenge_cap_per_team_game: int = int(os.getenv("CHALLENGE_CAP_PER_TEAM_GAME", "2"))


settings = Settings()
