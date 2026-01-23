from fastapi import APIRouter, HTTPException
from datetime import datetime
import re
import asyncio
import threading
import subprocess
from backend.models import (
    Task, TaskCreate, TaskUpdate, TaskStatus, PhaseConfigUpdate,
    Phase, PhaseConfig, PhaseStatus
)
from backend.database import (
    get_all_tasks, get_task, create_task as db_create_task,
    update_task, delete_task as db_delete_task
)
from backend.config import settings
from backend.services.worktree_manager import WorktreeManager
from backend.services.phase_executor import execute_all_phases
from backend.websocket_manager import manager

router = APIRouter()


def generate_task_id(title: str, existing_tasks: list[Task]) -> str:
    """Generate task ID in format: 001-slug-name"""
    existing_ids = [int(t.id.split("-")[0]) for t in existing_tasks if t.id.split("-")[0].isdigit()]
    next_num = max(existing_ids, default=0) + 1

    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:30]
    return f"{next_num:03d}-{slug}"


def create_default_phases(agent_profile: str = "balanced") -> dict[str, Phase]:
    """Create default phases for a new task based on agent profile"""
    profile_configs = {
        "quick": {
            "model": "claude-sonnet-4-20250514",
            "planning_turns": 10,
            "coding_turns": 15,
            "validation_turns": 10
        },
        "balanced": {
            "model": "claude-sonnet-4-20250514",
            "planning_turns": 20,
            "coding_turns": 30,
            "validation_turns": 20
        },
        "thorough": {
            "model": "claude-opus-4-20250514",
            "planning_turns": 30,
            "coding_turns": 50,
            "validation_turns": 30
        }
    }

    config = profile_configs.get(agent_profile, profile_configs["balanced"])

    return {
        "planning": Phase(
            name="planning",
            config=PhaseConfig(
                model=config["model"],
                intensity=settings.default_intensity,
                max_turns=config["planning_turns"]
            )
        ),
        "coding": Phase(
            name="coding",
            config=PhaseConfig(
                model=config["model"],
                intensity=settings.default_intensity,
                max_turns=config["coding_turns"]
            )
        ),
        "validation": Phase(
            name="validation",
            config=PhaseConfig(
                model=config["model"],
                intensity=settings.default_intensity,
                max_turns=config["validation_turns"]
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

    title = task_data.title
    if not title:
        title = f"Task: {task_data.description[:50]}..."

    task_id = generate_task_id(title, existing_tasks)

    phases = create_default_phases(task_data.agent_profile)

    if task_data.phase_config:
        for phase_name, phase_update in task_data.phase_config.items():
            if phase_name in phases:
                if phase_update.model is not None:
                    phases[phase_name].config.model = phase_update.model
                if phase_update.intensity is not None:
                    phases[phase_name].config.intensity = phase_update.intensity
                if phase_update.max_turns is not None:
                    phases[phase_name].config.max_turns = phase_update.max_turns

    task = Task(
        id=task_id,
        title=title,
        description=task_data.description,
        status=TaskStatus.BACKLOG,
        phases=phases,
        skip_ai_review=task_data.skip_ai_review
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
    if task_data.skip_ai_review is not None:
        task.skip_ai_review = task_data.skip_ai_review

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


async def execute_task_background(task_id: str, project_path: str):
    """Background task to execute all phases of a task"""
    print(f"[DEBUG] Background task started for task {task_id}")

    task = await get_task(task_id)
    if not task:
        print(f"[DEBUG] Task {task_id} not found")
        return

    print(f"[DEBUG] Task loaded: {task.title}")
    worktree_mgr = WorktreeManager(project_path)

    log_handler_count = 0

    async def log_handler(message: str):
        nonlocal log_handler_count
        log_handler_count += 1
        print(f"[LOG] (count: {log_handler_count}) {message}")
        await manager.send_log(task_id, message)

    try:
        await log_handler(f"Starting task execution: {task.title}")

        branch_name = f"task/{task.id}"
        await log_handler(f"Creating worktree for branch: {branch_name}")

        worktree_path = worktree_mgr.create(task.id, branch_name)
        task.worktree_path = str(worktree_path)
        task.branch_name = branch_name
        await update_task(task)

        await log_handler(f"Worktree created at: {worktree_path}")

        result = await execute_all_phases(task, str(worktree_path), log_handler)

        if result["success"]:
            if task.skip_ai_review:
                task.status = TaskStatus.HUMAN_REVIEW
                await log_handler("\n=== All phases completed successfully (AI Review skipped) ===")
            else:
                task.status = TaskStatus.AI_REVIEW
                await log_handler("\n=== All phases completed successfully ===")
        else:
            task.status = TaskStatus.IN_PROGRESS
            await log_handler("\n=== Execution stopped due to errors ===")

        task.updated_at = datetime.now()
        await update_task(task)

        await log_handler(f"\nTask status updated to: {task.status.value}")

    except Exception as e:
        await log_handler(f"\nERROR: {str(e)}")
        task.status = TaskStatus.BACKLOG
        task.updated_at = datetime.now()
        await update_task(task)


@router.post("/tasks/{task_id}/start")
async def start_task(task_id: str):
    """Start task execution"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == TaskStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Task is already running")

    task.status = TaskStatus.IN_PROGRESS
    task.updated_at = datetime.now()
    await update_task(task)

    asyncio.create_task(execute_task_background(task_id, settings.project_path))

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


@router.post("/tasks/{task_id}/create-pr")
async def create_pull_request(task_id: str):
    """Create a pull request for the task"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskStatus.HUMAN_REVIEW:
        raise HTTPException(status_code=400, detail="Task must be in human_review status")

    if not task.branch_name:
        raise HTTPException(status_code=400, detail="Task has no branch")

    if not task.worktree_path:
        raise HTTPException(status_code=400, detail="Task has no worktree")

    # Check if there are commits on the branch
    try:
        check_commits = subprocess.run(
            ["git", "log", "--oneline", f"develop..{task.branch_name}"],
            cwd=task.worktree_path,
            capture_output=True,
            text=True,
            check=True
        )

        if not check_commits.stdout.strip():
            raise HTTPException(status_code=400, detail="No commits found on branch. Cannot create PR without changes.")
    except subprocess.CalledProcessError:
        raise HTTPException(status_code=500, detail="Failed to check commits on branch")

    # Push the branch to remote
    try:
        subprocess.run(
            ["git", "push", "-u", "origin", task.branch_name],
            cwd=task.worktree_path,
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        raise HTTPException(status_code=500, detail=f"Failed to push branch: {error_msg}")

    try:
        result = subprocess.run(
            [
                "gh", "pr", "create",
                "--base", "develop",
                "--head", task.branch_name,
                "--title", task.title,
                "--body", task.description
            ],
            capture_output=True,
            text=True,
            check=True
        )

        pr_url = result.stdout.strip()

        task.pr_url = pr_url
        task.status = TaskStatus.DONE
        task.updated_at = datetime.now()
        await update_task(task)

        return {"message": "PR created", "pr_url": pr_url, "task": task}

    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="GitHub CLI (gh) is not installed")
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        raise HTTPException(status_code=500, detail=f"Failed to create PR: {error_msg}")
