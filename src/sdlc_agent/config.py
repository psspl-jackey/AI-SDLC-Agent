"""Settings loaded from environment variables (.env supported)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    model_provider: str
    ollama_url: str
    ollama_model: str
    anthropic_model: str
    cost_input_per_mtok: float
    cost_output_per_mtok: float
    data_dir: Path
    max_tokens: int
    risk_buffer_pct: float = 15.0
    jira_project_key: str = "SDLC"
    sprint_weeks: int = 2
    sprint_capacity_hours: float = 240.0

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def traces_dir(self) -> Path:
        return self.data_dir / "traces"


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        model_provider=os.getenv("MODEL_PROVIDER", "ollama").lower(),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:14b"),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        cost_input_per_mtok=float(os.getenv("COST_INPUT_PER_MTOK", "0")),
        cost_output_per_mtok=float(os.getenv("COST_OUTPUT_PER_MTOK", "0")),
        data_dir=Path(os.getenv("DATA_DIR", "./data")),
        max_tokens=int(os.getenv("MAX_TOKENS", "4096")),
        risk_buffer_pct=float(os.getenv("RISK_BUFFER_PCT", "15")),
        jira_project_key=os.getenv("JIRA_PROJECT_KEY", "SDLC").strip().upper() or "SDLC",
        sprint_weeks=int(os.getenv("SPRINT_WEEKS", "2")),
        sprint_capacity_hours=float(os.getenv("SPRINT_CAPACITY_HOURS", "240")),
    )
