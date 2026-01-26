from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from backend.models import GlobalConfig
from backend.config import settings as app_settings

router = APIRouter()


def get_storage():
    """Get storage instance (lazy import to avoid circular dependency)"""
    from backend.main import storage
    return storage


def get_task_queue():
    """Get task queue instance (lazy import to avoid circular dependency)"""
    from backend.services.task_queue import task_queue
    return task_queue


class MaxParallelUpdate(BaseModel):
    """Request body for updating max parallel tasks"""
    max_parallel_tasks: int = Field(..., ge=1, le=10, description="Maximum parallel tasks (1-10)")


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
        auto_review=app_settings.auto_review,
        max_parallel_tasks=app_settings.max_parallel_tasks
    )
    storage.set_config("global", default_config.model_dump())
    return default_config


@router.patch("/settings")
async def update_settings(config: GlobalConfig):
    """Update global configuration"""
    storage = get_storage()

    # If max_parallel_tasks changed, update the task queue
    old_config = storage.get_config("global") or {}
    if config.max_parallel_tasks != old_config.get("max_parallel_tasks"):
        task_queue = get_task_queue()
        await task_queue.update_max_concurrent(config.max_parallel_tasks)

    storage.set_config("global", config.model_dump())
    return config


@router.get("/settings/parallel")
async def get_parallel_settings():
    """Get parallel execution settings including current queue state"""
    storage = get_storage()
    task_queue = get_task_queue()

    config_data = storage.get_config("global")
    max_parallel = config_data.get("max_parallel_tasks", app_settings.max_parallel_tasks) if config_data else app_settings.max_parallel_tasks

    return {
        "max_parallel_tasks": max_parallel,
        "current_running": len(task_queue._running_tasks) + len(task_queue._direct_running),
        "current_queued": len(task_queue._priority_heap),
        "is_paused": task_queue.is_paused()
    }


@router.patch("/settings/parallel")
async def update_parallel_settings(data: MaxParallelUpdate):
    """
    Update max parallel tasks setting.

    This updates both the stored configuration and the live task queue.
    """
    storage = get_storage()
    task_queue = get_task_queue()

    # Validate range
    if not 1 <= data.max_parallel_tasks <= 10:
        raise HTTPException(status_code=400, detail="max_parallel_tasks must be between 1 and 10")

    # Update task queue
    success = await task_queue.update_max_concurrent(data.max_parallel_tasks)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update task queue")

    # Update stored config
    config_data = storage.get_config("global")
    if config_data:
        config_data["max_parallel_tasks"] = data.max_parallel_tasks
        storage.set_config("global", config_data)
    else:
        default_config = GlobalConfig(
            default_model=app_settings.default_model,
            default_intensity=app_settings.default_intensity,
            project_path=app_settings.project_path,
            auto_review=app_settings.auto_review,
            max_parallel_tasks=data.max_parallel_tasks
        )
        storage.set_config("global", default_config.model_dump())

    return {
        "max_parallel_tasks": data.max_parallel_tasks,
        "message": f"Max parallel tasks updated to {data.max_parallel_tasks}"
    }
