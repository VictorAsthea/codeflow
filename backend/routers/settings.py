from fastapi import APIRouter
import json
from backend.models import GlobalConfig
from backend.database import get_config, set_config
from backend.config import settings as app_settings

router = APIRouter()


@router.get("/settings")
async def get_settings():
    """Get global configuration"""
    config_str = await get_config("global")

    if config_str:
        config_data = json.loads(config_str)
        return GlobalConfig(**config_data)

    default_config = GlobalConfig(
        default_model=app_settings.default_model,
        default_intensity=app_settings.default_intensity,
        project_path=app_settings.project_path,
        auto_review=app_settings.auto_review
    )
    await set_config("global", json.dumps(default_config.model_dump()))
    return default_config


@router.patch("/settings")
async def update_settings(config: GlobalConfig):
    """Update global configuration"""
    await set_config("global", json.dumps(config.model_dump()))
    return config
