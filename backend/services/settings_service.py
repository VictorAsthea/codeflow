"""
Settings service for managing global configuration
"""
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
from backend.models import GlobalConfig
from backend.config import settings as app_settings


class SettingsService:
    """Service for managing global settings and configuration"""

    VALID_MODELS = [
        "claude-haiku-4-20250514",
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514"
    ]

    VALID_TARGET_BRANCHES = ["main", "develop"]
    VALID_INTENSITIES = ["low", "medium", "high"]

    def __init__(self, storage):
        """Initialize settings service with storage backend"""
        self.storage = storage

    async def get_settings(self) -> GlobalConfig:
        """Get current global configuration with defaults"""
        config_data = self.storage.get_config("global")

        if config_data:
            # Migrate old configs to new structure if needed
            config_data = self._migrate_config(config_data)
            try:
                return GlobalConfig(**config_data)
            except Exception:
                # If validation fails, fallback to default
                pass

        # Return default configuration
        return self._get_default_config()

    async def update_settings(self, settings: GlobalConfig) -> GlobalConfig:
        """Update global configuration with validation"""
        # Validate settings
        self._validate_settings(settings)

        # Save to storage
        self.storage.set_config("global", settings.model_dump())

        return settings

    async def reset_to_defaults(self) -> GlobalConfig:
        """Reset configuration to default values"""
        default_config = self._get_default_config()
        self.storage.set_config("global", default_config.model_dump())
        return default_config

    def _get_default_config(self) -> GlobalConfig:
        """Get default configuration values"""
        return GlobalConfig(
            # General
            project_path=app_settings.project_path,
            target_branch="main",

            # Legacy (keep for compatibility)
            default_model=app_settings.default_model,
            default_intensity=app_settings.default_intensity,
            auto_review=app_settings.auto_review,

            # Agents
            max_parallel_tasks=3,

            # Models
            planning_model="claude-sonnet-4-20250514",
            coding_model="claude-sonnet-4-20250514",
            validation_model="claude-haiku-4-20250514",

            # Git
            auto_create_pr=True,
            pr_template=None,

            # Notifications
            enable_sounds=True,
            enable_desktop_notifications=False
        )

    def _validate_settings(self, settings: GlobalConfig) -> None:
        """Validate settings before saving"""
        # Validate project path
        if settings.project_path:
            project_path = Path(settings.project_path)
            if not project_path.exists():
                raise ValueError(f"Project path does not exist: {settings.project_path}")
            if not project_path.is_dir():
                raise ValueError(f"Project path is not a directory: {settings.project_path}")

        # Validate target branch
        if settings.target_branch not in self.VALID_TARGET_BRANCHES:
            raise ValueError(f"Invalid target branch: {settings.target_branch}")

        # Validate models
        if settings.planning_model not in self.VALID_MODELS:
            raise ValueError(f"Invalid planning model: {settings.planning_model}")
        if settings.coding_model not in self.VALID_MODELS:
            raise ValueError(f"Invalid coding model: {settings.coding_model}")
        if settings.validation_model not in self.VALID_MODELS:
            raise ValueError(f"Invalid validation model: {settings.validation_model}")

        # Validate legacy settings
        if settings.default_model not in self.VALID_MODELS:
            raise ValueError(f"Invalid default model: {settings.default_model}")
        if settings.default_intensity not in self.VALID_INTENSITIES:
            raise ValueError(f"Invalid default intensity: {settings.default_intensity}")

        # Validate parallel tasks range (handled by Pydantic Field but double-check)
        if not (1 <= settings.max_parallel_tasks <= 10):
            raise ValueError("Max parallel tasks must be between 1 and 10")

    def _migrate_config(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate old configuration format to new one"""
        # Set default values for missing fields
        defaults = {
            "target_branch": "main",
            "max_parallel_tasks": 3,
            "planning_model": "claude-sonnet-4-20250514",
            "coding_model": "claude-sonnet-4-20250514",
            "validation_model": "claude-haiku-4-20250514",
            "auto_create_pr": True,
            "pr_template": None,
            "enable_sounds": True,
            "enable_desktop_notifications": False
        }

        # Add missing fields with defaults
        for key, default_value in defaults.items():
            if key not in config_data:
                config_data[key] = default_value

        return config_data

    def get_model_options(self) -> list[dict]:
        """Get available model options for UI"""
        return [
            {"value": "claude-haiku-4-20250514", "label": "Claude Haiku 4 (Fast)"},
            {"value": "claude-sonnet-4-20250514", "label": "Claude Sonnet 4 (Balanced)"},
            {"value": "claude-opus-4-20250514", "label": "Claude Opus 4 (Powerful)"}
        ]

    def get_target_branch_options(self) -> list[dict]:
        """Get available target branch options for UI"""
        return [
            {"value": "main", "label": "main"},
            {"value": "develop", "label": "develop"}
        ]

    def get_intensity_options(self) -> list[dict]:
        """Get available intensity options for UI"""
        return [
            {"value": "low", "label": "Low"},
            {"value": "medium", "label": "Medium"},
            {"value": "high", "label": "High"}
        ]