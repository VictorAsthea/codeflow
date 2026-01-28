from pydantic_settings import BaseSettings
from pathlib import Path


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

    # Cleanup settings - auto-cleanup test/debug files before Human Review
    cleanup_enabled: bool = True
    cleanup_patterns: list[str] = [
        # Test files
        "test_*.py",
        "*_test.py",
        "*.test.ts",
        "*.test.tsx",
        "*.test.js",
        "*.test.jsx",
        "*.spec.ts",
        "*.spec.tsx",
        "*.spec.js",
        "*.spec.jsx",
        # Spec/debug documentation
        "*-spec.md",
        "*-debug.md",
        # Cache directories
        ".pytest_cache/",
        "__pycache__/",
        ".mypy_cache/",
        # Debug scripts
        "scripts/debug_*.py",
        "scripts/test_*.py",
        # Build artifacts that shouldn't be committed
        "*.pyc",
        "*.pyo",
    ]
    cleanup_keep_patterns: list[str] = [
        # Keep actual test suites in tests/ directories
        "tests/**",
        "test/**",
        "__tests__/**",
        # Keep CI/CD test configurations
        ".github/**",
        "pytest.ini",
        "jest.config.*",
        "vitest.config.*",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
