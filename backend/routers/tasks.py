from fastapi import APIRouter, HTTPException
from datetime import datetime
import re
from backend.models import (
    Task, TaskCreate, TaskUpdate, TaskStatus, PhaseConfigUpdate,
    Phase, PhaseConfig, PhaseStatus
)
from backend.database import (
    get_all_tasks, get_task, create_task as db_create_task,
    update_task, delete_task as db_delete_task
)
from backend.config import settings

router = APIRouter()


def generate_task_id(title: str, existing_tasks: list[Task]) -> str:
    """Generate task ID in format: 001-slug-name"""
    existing_ids = [int(t.id.split("-")[0]) for t in existing_tasks if t.id.split("-")[0].isdigit()]
    next_num = max(existing_ids, default=0) + 1

    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:30]
    return f"{next_num:03d}-{slug}"


def create_default_phases() -> dict[str, Phase]:
    """Create default phases for a new task"""
    return {
        "planning": Phase(
            name="planning",
            config=PhaseConfig(
                model=settings.default_model,
                intensity=settings.default_intensity
            )
        ),
        "coding": Phase(
            name="coding",
            config=PhaseConfig(
                model=settings.default_model,
                intensity=settings.default_intensity
            )
        ),
        "validation": Phase(
            name="validation",
            config=PhaseConfig(
                model=settings.default_model,
                intensity=settings.default_intensity
            )
        )
    }


@router.get("/tasks")
async def list_tasks():
    """List all tasks"""
    tasks = await get_all_tasks()
    return {"tasks": tasks}


@router.post("/tasks")
async def create_new_task(task_data: TaskCreate):
    """Create a new task"""
    existing_tasks = await get_all_tasks()
    task_id = generate_task_id(task_data.title, existing_tasks)

    task = Task(
        id=task_id,
        title=task_data.title,
        description=task_data.description,
        status=TaskStatus.BACKLOG,
        phases=create_default_phases()
    )

    await db_create_task(task)
    return task


@router.get("/tasks/{task_id}")
async def get_task_detail(task_id: str):
    """Get task detail"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/tasks/{task_id}")
async def update_task_detail(task_id: str, task_data: TaskUpdate):
    """Update task"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task_data.title is not None:
        task.title = task_data.title
    if task_data.description is not None:
        task.description = task_data.description
    if task_data.status is not None:
        task.status = task_data.status

    task.updated_at = datetime.now()
    await update_task(task)
    return task


@router.delete("/tasks/{task_id}")
async def delete_task_endpoint(task_id: str):
    """Delete a task"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    await db_delete_task(task_id)
    return {"message": "Task deleted successfully"}


@router.post("/tasks/{task_id}/start")
async def start_task(task_id: str):
    """Start task execution"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = TaskStatus.IN_PROGRESS
    task.updated_at = datetime.now()
    await update_task(task)

    return {"message": "Task started", "task": task}


@router.post("/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    """Stop task execution"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = TaskStatus.BACKLOG
    task.updated_at = datetime.now()
    await update_task(task)

    return {"message": "Task stopped", "task": task}


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str):
    """Resume a task"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = TaskStatus.IN_PROGRESS
    task.updated_at = datetime.now()
    await update_task(task)

    return {"message": "Task resumed", "task": task}


@router.patch("/tasks/{task_id}/status")
async def change_task_status(task_id: str, status_data: dict):
    """Change task status (for drag & drop)"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    new_status = status_data.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="Status is required")

    try:
        task.status = TaskStatus(new_status)
        task.updated_at = datetime.now()
        await update_task(task)
        return task
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid status")


@router.patch("/tasks/{task_id}/phases/{phase_name}")
async def update_phase_config(task_id: str, phase_name: str, config_data: PhaseConfigUpdate):
    """Update phase configuration"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if phase_name not in task.phases:
        raise HTTPException(status_code=404, detail="Phase not found")

    phase = task.phases[phase_name]

    if config_data.model is not None:
        phase.config.model = config_data.model
    if config_data.intensity is not None:
        phase.config.intensity = config_data.intensity
    if config_data.max_turns is not None:
        phase.config.max_turns = config_data.max_turns

    task.updated_at = datetime.now()
    await update_task(task)
    return {"message": "Phase config updated", "phase": phase}


@router.post("/tasks/{task_id}/phases/{phase_name}/retry")
async def retry_phase(task_id: str, phase_name: str):
    """Retry a failed phase"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if phase_name not in task.phases:
        raise HTTPException(status_code=404, detail="Phase not found")

    phase = task.phases[phase_name]
    phase.status = PhaseStatus.PENDING
    phase.logs = []
    phase.started_at = None
    phase.completed_at = None

    task.updated_at = datetime.now()
    await update_task(task)
    return {"message": "Phase reset for retry", "phase": phase}
