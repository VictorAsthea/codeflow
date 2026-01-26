"""
Settings service for managing global configuration
"""
import logging
from pathlib import Path
from pydantic import ValidationError
from typing import Dict, Any, Optional
from backend.models import GlobalConfig
from backend.config import settings as app_settings
from backend.services.project_config_service import get_project_config


logger = logging.getLogger(__name__)


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

    async def get_settings(self, project_path: Optional[str] = None) -> GlobalConfig:
        """
        Get current configuration with project-specific overrides.

        Priority:
        1. Project .codeflow/config.json settings
        2. Global config from storage
        3. Default configuration
        """
        # Start with default config
        config = self._get_default_config()

        # Try to load global config from storage
        config_data = self.storage.get_config("global")
        if config_data:
            try:
                config = GlobalConfig(**config_data)
            except ValidationError as e:
                logger.warning(f"Failed to load GlobalConfig from config_data: {e}")

        # Override with project-specific settings from .codeflow/config.json
        try:
            project_config = get_project_config(project_path)
            if project_config.is_initialized():
                project_settings = project_config.get_settings()

                # Apply project overrides
                if "default_branch" in project_settings:
                    config.target_branch = project_settings["default_branch"]
                if "auto_commit" in project_settings:
                    # Map to closest global setting
                    pass  # Could add auto_commit to GlobalConfig later
                if "auto_push" in project_settings:
                    # Map to closest global setting
                    pass  # Could add auto_push to GlobalConfig later

                logger.debug(f"Applied project settings from {project_config.project_path}")

        except Exception as e:
            logger.warning(f"Failed to load project config: {e}")

        return config

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
        if not settings.project_path or not settings.project_path.strip():
            raise ValueError("Project path is required")
        project_path = Path(settings.project_path)
        if not project_path.exists():
            raise ValueError(f"Project path does not exist: {settings.project_path}")
        if not project_path.is_dir():
            raise ValueError(f"Project path is not a directory: {settings.project_path}")

        # Validate target branch
        if settings.target_branch not in self.VALID_TARGET_BRANCHES:
            raise ValueError(f"Invalid target branch: {settings.target_branch}")

        # Validate models
        models_to_validate = {
            "planning": settings.planning_model,
            "coding": settings.coding_model,
            "validation": settings.validation_model,
            "default": settings.default_model,
        }
        for name, model in models_to_validate.items():
            if model not in self.VALID_MODELS:
                raise ValueError(f"Invalid {name} model: {model}")

        # Validate legacy settings
        if settings.default_intensity not in self.VALID_INTENSITIES:
            raise ValueError(f"Invalid default intensity: {settings.default_intensity}")

        # Validate parallel tasks range (handled by Pydantic Field but double-check)
        if not (1 <= settings.max_parallel_tasks <= 10):
            raise ValueError("Max parallel tasks must be between 1 and 10")


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