from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any
from backend.models import GlobalConfig, RetryConfig, RecoverableErrorType
from backend.config import settings as app_settings

router = APIRouter()


# ============== Retry Configuration Models ==============

class RetryConfigUpdate(BaseModel):
    """Request body for updating retry configuration."""
    max_retries: int | None = Field(default=None, ge=0, le=10, description="Max retry attempts (0-10)")
    base_delay: float | None = Field(default=None, ge=0.1, le=60.0, description="Base delay in seconds")
    multiplier: float | None = Field(default=None, ge=1.0, le=5.0, description="Backoff multiplier")
    jitter_factor: float | None = Field(default=None, ge=0.0, le=0.5, description="Jitter factor (±)")
    max_total_timeout: float | None = Field(default=None, ge=60.0, le=7200.0, description="Max total timeout in seconds")
    recoverable_error_types: list[str] | None = Field(default=None, description="Error types to retry")
    recoverable_http_codes: list[int] | None = Field(default=None, description="HTTP codes to retry")


class CircuitBreakerConfigUpdate(BaseModel):
    """Request body for updating circuit breaker configuration."""
    enabled: bool | None = Field(default=None, description="Enable/disable circuit breaker")
    failure_threshold: int | None = Field(default=None, ge=1, le=20, description="Failures before opening")
    recovery_timeout: float | None = Field(default=None, ge=10.0, le=3600.0, description="Recovery timeout in seconds")


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


# ============== Retry Metrics Endpoints ==============

@router.get("/settings/retry-metrics")
async def get_retry_metrics() -> dict[str, Any]:
    """
    Get retry system metrics.

    Returns aggregated statistics about retry operations including:
    - total_retries: Total number of operations that triggered retries
    - successful_retries: Operations that eventually succeeded after retry
    - failed_retries: Operations that failed after exhausting all retries
    - success_rate: Percentage of successful retry operations
    - average_recovery_time: Mean time to recover from transient errors
    - error_type_distribution: Count of each error type encountered
    """
    from backend.services.retry_metrics import get_retry_metrics as get_metrics
    metrics = get_metrics()
    return metrics.get_metrics()


@router.get("/settings/retry-metrics/recent")
async def get_recent_retry_records(limit: int = 10) -> dict[str, Any]:
    """
    Get recent retry operation records.

    Args:
        limit: Maximum number of records to return (default: 10, max: 100)

    Returns:
        List of recent retry records with detailed information
    """
    from backend.services.retry_metrics import get_retry_metrics as get_metrics

    if limit < 1:
        limit = 1
    elif limit > 100:
        limit = 100

    metrics = get_metrics()
    return {
        "records": metrics.get_recent_records(limit),
        "limit": limit
    }


@router.post("/settings/retry-metrics/reset")
async def reset_retry_metrics() -> dict[str, str]:
    """
    Reset all retry metrics to their initial state.

    This clears all aggregated statistics and recent records.
    Use with caution as this action cannot be undone.
    """
    from backend.services.retry_metrics import get_retry_metrics as get_metrics
    metrics = get_metrics()
    metrics.reset()
    return {"message": "Retry metrics reset successfully"}


# ============== Retry Configuration Endpoints ==============

@router.get("/settings/retry-config")
async def get_retry_config() -> dict[str, Any]:
    """
    Get current retry system configuration.

    Returns:
        Current retry configuration including backoff settings,
        recoverable error types, and timeout values.
    """
    storage = get_storage()

    # Try to get project-specific config first
    config_data = storage.get_config("retry")

    if config_data:
        return {
            "config": config_data,
            "source": "stored",
            "circuit_breaker": _get_circuit_breaker_config()
        }

    # Return default configuration from app settings
    return {
        "config": {
            "max_retries": app_settings.retry_max_attempts,
            "base_delay": app_settings.retry_base_delay,
            "multiplier": app_settings.retry_multiplier,
            "jitter_factor": app_settings.retry_jitter_factor,
            "max_total_timeout": app_settings.retry_max_total_timeout,
            "recoverable_error_types": [e.value for e in RecoverableErrorType],
            "recoverable_http_codes": [429, 502, 503, 504, 520, 521, 522, 523, 524],
        },
        "source": "default",
        "circuit_breaker": _get_circuit_breaker_config()
    }


@router.put("/settings/retry-config")
async def update_retry_config(data: RetryConfigUpdate) -> dict[str, Any]:
    """
    Update retry system configuration.

    Partial updates are supported - only provided fields will be updated.
    Changes take effect for new retry operations.

    Args:
        data: Fields to update in the retry configuration

    Returns:
        Updated configuration
    """
    storage = get_storage()

    # Get existing config or create default
    existing = storage.get_config("retry") or {
        "max_retries": app_settings.retry_max_attempts,
        "base_delay": app_settings.retry_base_delay,
        "multiplier": app_settings.retry_multiplier,
        "jitter_factor": app_settings.retry_jitter_factor,
        "max_total_timeout": app_settings.retry_max_total_timeout,
        "recoverable_error_types": [e.value for e in RecoverableErrorType],
        "recoverable_http_codes": [429, 502, 503, 504, 520, 521, 522, 523, 524],
    }

    # Update only provided fields
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            existing[key] = value

    # Validate HTTP codes
    if "recoverable_http_codes" in update_data:
        for code in existing["recoverable_http_codes"]:
            if not (400 <= code <= 599):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid HTTP code {code}. Must be between 400-599."
                )

    # Save updated config
    storage.set_config("retry", existing)

    return {
        "config": existing,
        "message": "Retry configuration updated successfully"
    }


@router.delete("/settings/retry-config")
async def reset_retry_config() -> dict[str, str]:
    """
    Reset retry configuration to default values.

    This removes any stored configuration and reverts to application defaults.
    """
    storage = get_storage()
    storage.set_config("retry", None)  # Clear stored config

    return {"message": "Retry configuration reset to defaults"}


# ============== Circuit Breaker Endpoints ==============

def _get_circuit_breaker_config() -> dict[str, Any]:
    """Helper to get circuit breaker configuration and status."""
    from backend.services.retry_manager import get_circuit_breaker_status
    return get_circuit_breaker_status()


@router.get("/settings/circuit-breaker")
async def get_circuit_breaker_status() -> dict[str, Any]:
    """
    Get current circuit breaker status and configuration.

    Returns:
        Circuit breaker state, configuration, and timing information
    """
    from backend.services.retry_manager import get_circuit_breaker_status as get_status
    return get_status()


@router.put("/settings/circuit-breaker")
async def update_circuit_breaker_config(data: CircuitBreakerConfigUpdate) -> dict[str, Any]:
    """
    Update circuit breaker configuration.

    Note: Changes to configuration require a server restart to take full effect
    on the global circuit breaker instance. However, the enabled state can be
    toggled immediately.

    Args:
        data: Fields to update in the circuit breaker configuration
    """
    storage = get_storage()

    # Get existing config
    existing = storage.get_config("circuit_breaker") or {
        "enabled": app_settings.circuit_breaker_enabled,
        "failure_threshold": app_settings.circuit_breaker_failure_threshold,
        "recovery_timeout": app_settings.circuit_breaker_recovery_timeout,
    }

    # Update only provided fields
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            existing[key] = value

    storage.set_config("circuit_breaker", existing)

    # If enabled state changed, update the global circuit breaker
    if "enabled" in update_data:
        from backend.services.retry_manager import get_global_circuit_breaker
        breaker = get_global_circuit_breaker()
        breaker.enabled = existing["enabled"]

    return {
        "config": existing,
        "message": "Circuit breaker configuration updated. Some changes may require restart.",
        "current_status": _get_circuit_breaker_config()
    }


@router.post("/settings/circuit-breaker/reset")
async def reset_circuit_breaker() -> dict[str, Any]:
    """
    Manually reset the circuit breaker to closed state.

    This can be used to recover from an open circuit breaker state
    when you believe the underlying issue has been resolved.
    """
    from backend.services.retry_manager import reset_circuit_breaker as do_reset
    do_reset()

    return {
        "message": "Circuit breaker reset to closed state",
        "status": _get_circuit_breaker_config()
    }
