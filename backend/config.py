from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/codeflow.db"
    host: str = "127.0.0.1"
    port: int = 8765
    project_path: str = str(Path.cwd())
    default_model: str = "claude-sonnet-4-5-20250929"
    default_intensity: str = "medium"
    auto_review: bool = True

    # Auto-resume settings for max_turns limit
    auto_resume_enabled: bool = True
    auto_resume_max_retries: int = 3
    auto_resume_delay_seconds: int = 2

    # Parallel task execution
    max_parallel_tasks: int = 3

    # PR monitoring settings
    pr_monitoring_enabled: bool = True
    pr_check_interval: int = 300
    github_webhook_secret: str | None = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
