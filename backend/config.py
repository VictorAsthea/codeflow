from pydantic_settings import BaseSettings
from pathlib import Path
from backend.models import PhaseConfig


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/codeflow.db"
    host: str = "127.0.0.1"
    port: int = 8765
    project_path: str = str(Path.cwd())
    default_model: str = "claude-sonnet-4-5-20250929"
    default_intensity: str = "medium"
    auto_review: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()


AGENT_PROFILES = {
    "quick": {
        "planning": PhaseConfig(model="claude-sonnet-4-5-20250929", intensity="medium", max_turns=10),
        "coding": PhaseConfig(model="claude-sonnet-4-5-20250929", intensity="medium", max_turns=20),
        "validation": PhaseConfig(model="claude-sonnet-4-5-20250929", intensity="medium", max_turns=10)
    },
    "balanced": {
        "planning": PhaseConfig(model="claude-sonnet-4-5-20250929", intensity="medium", max_turns=20),
        "coding": PhaseConfig(model="claude-sonnet-4-5-20250929", intensity="medium", max_turns=30),
        "validation": PhaseConfig(model="claude-sonnet-4-5-20250929", intensity="medium", max_turns=20)
    },
    "thorough": {
        "planning": PhaseConfig(model="claude-opus-4-5-20251101", intensity="high", max_turns=30),
        "coding": PhaseConfig(model="claude-opus-4-5-20251101", intensity="high", max_turns=50),
        "validation": PhaseConfig(model="claude-opus-4-5-20251101", intensity="high", max_turns=30)
    }
}
