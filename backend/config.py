from pydantic_settings import BaseSettings
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.models import RetryConfig


# Agent profiles for different task execution strategies
AGENT_PROFILES = {
    "quick": {
        "planning": {"model": "claude-haiku-4-20250514", "intensity": "low", "max_turns": 5},
        "coding": {"model": "claude-sonnet-4-20250514", "intensity": "low", "max_turns": 5}
    },
    "balanced": {
        "planning": {"model": "claude-sonnet-4-20250514", "intensity": "medium", "max_turns": 10},
        "coding": {"model": "claude-sonnet-4-20250514", "intensity": "medium", "max_turns": 10}
    },
    "thorough": {
        "planning": {"model": "claude-sonnet-4-20250514", "intensity": "high", "max_turns": 15},
        "coding": {"model": "claude-opus-4-20250514", "intensity": "high", "max_turns": 15}
    }
}


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

    # Code review settings
    code_review_auto: bool = True
    code_review_auto_fix: bool = True
    code_review_max_cycles: int = 2
    code_review_confidence_threshold: float = 80.0
    code_review_timeout: int = 60

    # v0.4 Model configuration per phase (for CLI)
    planning_model: str = "claude-sonnet-4-20250514"
    coding_model: str = "claude-sonnet-4-20250514"
    validation_model: str = "claude-haiku-4-20250514"

    # Retry system settings for Claude CLI execution
    retry_enabled: bool = True
    retry_max_attempts: int = 4
    retry_base_delay: float = 2.0
    retry_multiplier: float = 2.0
    retry_jitter_factor: float = 0.2
    retry_max_total_timeout: float = 1800.0  # 30 minutes max for all retries

    # Circuit breaker settings (prevents retries when system is unhealthy)
    circuit_breaker_enabled: bool = True
    circuit_breaker_failure_threshold: int = 5  # Consecutive failures to trigger
    circuit_breaker_recovery_timeout: float = 300.0  # 5 minutes before retry

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def get_retry_config(self) -> "RetryConfig":
        """Create a RetryConfig instance from current settings.

        Returns:
            RetryConfig: Configuration object for the retry system
        """
        from backend.models import RetryConfig
        return RetryConfig(
            max_retries=self.retry_max_attempts,
            base_delay=self.retry_base_delay,
            multiplier=self.retry_multiplier,
            jitter_factor=self.retry_jitter_factor,
            max_total_timeout=self.retry_max_total_timeout
        )


settings = Settings()
