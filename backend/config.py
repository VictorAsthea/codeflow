from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/codeflow.db"
    host: str = "127.0.0.1"
    port: int = 8765
    project_path: str = str(Path.cwd())
    default_model: str = "claude-sonnet-4-20250514"
    default_intensity: str = "medium"
    auto_review: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
