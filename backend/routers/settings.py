from fastapi import APIRouter
import json
from backend.models import GlobalConfig
from backend.config import settings as app_settings

router = APIRouter()


def get_storage():
    """Get storage instance (lazy import to avoid circular dependency)"""
    from backend.main import storage
    return storage


@router.get("/settings")
async def get_settings():
    """Get global configuration"""
    storage = get_storage()
    config_data = storage.get_config("global")

    if config_data:
        return GlobalConfig(**config_data)

    default_config = GlobalConfig(
        default_model=app_settings.default_model,
        default_intensity=app_settings.default_intensity,
        project_path=app_settings.project_path,
        auto_review=app_settings.auto_review
    )
    storage.set_config("global", default_config.model_dump())
    return default_config


@router.patch("/settings")
async def update_settings(config: GlobalConfig):
    """Update global configuration"""
    storage = get_storage()
    storage.set_config("global", config.model_dump())
    return config
