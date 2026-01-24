from fastapi import APIRouter, HTTPException
from datetime import datetime
import re
import asyncio
import threading
import subprocess
from backend.models import (
    Task, TaskCreate, TaskUpdate, TaskStatus, PhaseConfigUpdate,
    Phase, PhaseConfig, PhaseStatus, FixCommentsRequest
)
from backend.config import settings


def get_storage():
    """Get storage instance (lazy import to avoid circular dependency)"""
    from backend.main import storage
    return storage
from backend.services.worktree_manager import WorktreeManager
from backend.services.phase_executor import execute_all_phases
from backend.services.task_queue import task_queue
from backend.websocket_manager import manager

router = APIRouter()


def generate_task_id(title: str, existing_tasks: list[Task]) -> str:
    """Generate task ID in format: 001-slug-name"""
    existing_ids = [int(t.id.split("-")[0]) for t in existing_tasks if t.id.split("-")[0].isdigit()]
    next_num = max(existing_ids, default=0) + 1

    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:30]
    return f"{next_num:03d}-{slug}"


@router.get("/tasks")
async def list_tasks(include_archived: bool = False):
    """List all tasks"""
    tasks = get_storage().load_tasks()
    if not include_archived:
        tasks = [task for task in tasks if not task.archived]
    return {"tasks": tasks}


@router.post("/tasks")
async def create_new_task(task_data: TaskCreate):
    """Create a new task"""
    from backend.config import AGENT_PROFILES
    from backend.services.title_generator import generate_title

    title = task_data.title
    if not title:
        title = await generate_title(task_data.description)

    existing_tasks = get_storage().load_tasks()
    task_id = generate_task_id(title, existing_tasks)

    if task_data.planning_config:
        planning_config = task_data.planning_config
    else:
        planning_config = AGENT_PROFILES[task_data.agent_profile.value]["planning"]

    if task_data.coding_config:
        coding_config = task_data.coding_config
    else:
        coding_config = AGENT_PROFILES[task_data.agent_profile.value]["coding"]

    phases = {
        "planning": Phase(
            name="planning",
            config=planning_config
        ),
        "coding": Phase(
            name="coding",
            config=coding_config
        )
    }

    branch_name = None
    if task_data.git_options and task_data.git_options.branch_name:
        branch_name = task_data.git_options.branch_name
    else:
        branch_name = f"task/{task_id}"

    task = Task(
        id=task_id,
        title=title,
        description=task_data.description,
        status=TaskStatus.BACKLOG,
        phases=phases,
        branch_name=branch_name,
        skip_ai_review=task_data.skip_ai_review,
        agent_profile=task_data.agent_profile,
        require_human_review_before_coding=task_data.require_human_review_before_coding,
        file_references=task_data.file_references,
        screenshots=task_data.screenshots
    )

    get_storage().create_task(task)
    return task


@router.get("/tasks/{task_id}")
async def get_task_detail(task_id: str):
    """Get task detail"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/tasks/{task_id}")
async def update_task_detail(task_id: str, task_data: TaskUpdate):
    """Update task"""
    task = get_storage().get_task(task_id)
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
    get_storage().update_task(task)
    return task


@router.delete("/tasks/{task_id}")
async def delete_task_endpoint(task_id: str):
    """Delete a task"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    get_storage().delete_task(task_id)
    return {"message": "Task deleted successfully"}


@router.patch("/tasks/{task_id}/archive")
async def archive_task(task_id: str):
    """Archive a task"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.archived:
        raise HTTPException(status_code=400, detail="Task is already archived")

    task.archived = True
    task.archived_at = datetime.now()
    task.updated_at = datetime.now()
    get_storage().update_task(task)

    return {"message": "Task archived successfully", "task": task}


@router.patch("/tasks/{task_id}/unarchive")
async def unarchive_task(task_id: str):
    """Unarchive a task"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task.archived:
        raise HTTPException(status_code=400, detail="Task is not archived")

    task.archived = False
    task.archived_at = None
    task.updated_at = datetime.now()
    get_storage().update_task(task)

    return {"message": "Task unarchived successfully", "task": task}


async def execute_task_background(task_id: str, project_path: str):
    """Background task to execute all phases of a task"""
    print(f"[DEBUG] Background task started for task {task_id}")
    task_queue.register_direct_task(task_id)

    task = get_storage().get_task(task_id)
    if not task:
        print(f"[DEBUG] Task {task_id} not found")
        task_queue.unregister_direct_task(task_id)
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

        branch_name = task.branch_name or f"task/{task.id}"
        await log_handler(f"Creating worktree for branch: {branch_name}")

        worktree_path = worktree_mgr.create(task.id, branch_name)
        task.worktree_path = str(worktree_path)
        task.branch_name = branch_name
        get_storage().update_task(task)

        await log_handler(f"Worktree created at: {worktree_path}")

        result = await execute_all_phases(task, str(worktree_path), log_handler, manager)

        if result["success"]:
            if task.skip_ai_review or not settings.code_review_auto:
                task.status = TaskStatus.HUMAN_REVIEW
                await log_handler("\n=== All phases completed successfully (AI Review skipped) ===")
            else:
                task.status = TaskStatus.AI_REVIEW
                await log_handler("\n=== All phases completed successfully ===")

            task.updated_at = datetime.now()
            get_storage().update_task(task)

            # Run AI review if enabled
            if task.status == TaskStatus.AI_REVIEW:
                from backend.services.task_orchestrator import handle_ai_review
                await handle_ai_review(task, log_handler)
        else:
            task.status = TaskStatus.IN_PROGRESS
            await log_handler("\n=== Execution stopped due to errors ===")
            task.updated_at = datetime.now()
            get_storage().update_task(task)

        await log_handler(f"\nTask status updated to: {task.status.value}")

    except Exception as e:
        await log_handler(f"\nERROR: {str(e)}")
        task.status = TaskStatus.BACKLOG
        task.updated_at = datetime.now()
        get_storage().update_task(task)
    finally:
        task_queue.unregister_direct_task(task_id)


@router.post("/tasks/{task_id}/start")
async def start_task(task_id: str):
    """Start task execution immediately (bypasses queue)"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == TaskStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Task is already running")

    task.status = TaskStatus.IN_PROGRESS
    task.updated_at = datetime.now()
    get_storage().update_task(task)

    asyncio.create_task(execute_task_background(task_id, settings.project_path))

    return {"message": "Task started", "task": task}


@router.post("/tasks/{task_id}/queue")
async def queue_task(task_id: str):
    """Add task to the execution queue"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == TaskStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Task is already running")

    if task.status == TaskStatus.QUEUED:
        raise HTTPException(status_code=400, detail="Task is already queued")

    success = await task_queue.queue_task(task_id, settings.project_path)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to queue task")

    # Refresh task
    task = get_storage().get_task(task_id)
    return {"message": "Task queued", "task": task, "queue_status": task_queue.get_status()}


@router.delete("/tasks/{task_id}/queue")
async def unqueue_task(task_id: str):
    """Remove task from the queue"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskStatus.QUEUED:
        raise HTTPException(status_code=400, detail="Task is not queued")

    success = await task_queue.remove_from_queue(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Task not found in queue or already running")

    # Refresh task
    task = get_storage().get_task(task_id)
    return {"message": "Task removed from queue", "task": task}


@router.get("/queue/status")
async def get_queue_status():
    """Get current queue status"""
    return task_queue.get_status()


@router.post("/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    """Stop task execution"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = TaskStatus.BACKLOG
    task.updated_at = datetime.now()
    get_storage().update_task(task)

    return {"message": "Task stopped", "task": task}


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str):
    """Resume a task"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = TaskStatus.IN_PROGRESS
    task.updated_at = datetime.now()
    get_storage().update_task(task)

    return {"message": "Task resumed", "task": task}


@router.patch("/tasks/{task_id}/status")
async def change_task_status(task_id: str, status_data: dict):
    """Change task status (for drag & drop)"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    new_status = status_data.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="Status is required")

    try:
        task.status = TaskStatus(new_status)
        task.updated_at = datetime.now()
        get_storage().update_task(task)

        # Trigger AI review when dropped into ai_review column
        if new_status == "ai_review" and task.worktree_path:
            task.review_status = "in_progress"
            get_storage().update_task(task)

            async def run_ai_review():
                from backend.services.task_orchestrator import handle_ai_review
                # Reload task to get fresh state
                fresh_task = get_storage().get_task(task_id)
                async def log_handler(message: str):
                    await manager.send_log(task_id, message)
                await handle_ai_review(fresh_task, log_handler)

            asyncio.create_task(run_ai_review())

        return task
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid status")


@router.patch("/tasks/{task_id}/phases/{phase_name}")
async def update_phase_config(task_id: str, phase_name: str, config_data: PhaseConfigUpdate):
    """Update phase configuration"""
    task = get_storage().get_task(task_id)
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
    get_storage().update_task(task)
    return {"message": "Phase config updated", "phase": phase}


@router.post("/tasks/{task_id}/phases/{phase_name}/retry")
async def retry_phase(task_id: str, phase_name: str):
    """Retry a failed phase"""
    task = get_storage().get_task(task_id)
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
    get_storage().update_task(task)
    return {"message": "Phase reset for retry", "phase": phase}


@router.post("/tasks/{task_id}/review/accept")
async def accept_review(task_id: str):
    """Accept AI review and proceed to human review"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskStatus.AI_REVIEW:
        raise HTTPException(status_code=400, detail="Task must be in ai_review status")

    task.status = TaskStatus.HUMAN_REVIEW
    task.review_status = "accepted"
    task.updated_at = datetime.now()
    get_storage().update_task(task)

    return {"message": "Review accepted", "task": task}


@router.post("/tasks/{task_id}/review/skip")
async def skip_review(task_id: str):
    """Skip AI review and proceed to human review"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskStatus.AI_REVIEW:
        raise HTTPException(status_code=400, detail="Task must be in ai_review status")

    task.status = TaskStatus.HUMAN_REVIEW
    task.review_status = "skipped"
    task.updated_at = datetime.now()
    get_storage().update_task(task)

    return {"message": "Review skipped", "task": task}


@router.post("/tasks/{task_id}/review/retry")
async def retry_review_fixes(task_id: str):
    """Retry with auto-fix for review issues"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskStatus.AI_REVIEW:
        raise HTTPException(status_code=400, detail="Task must be in ai_review status")

    async def log_handler(message: str):
        await manager.send_log(task_id, message)

    from backend.services.task_orchestrator import retry_with_review_fixes

    asyncio.create_task(retry_with_review_fixes(task, log_handler))

    return {"message": "Retrying with fixes", "task": task}


@router.get("/tasks/{task_id}/review/status")
async def get_review_status(task_id: str):
    """Get review status for a task"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "task_id": task.id,
        "status": task.status.value,
        "review_status": task.review_status,
        "review_cycles": task.review_cycles,
        "review_issues": task.review_issues,
        "max_cycles": settings.code_review_max_cycles
    }


@router.post("/tasks/{task_id}/create-pr")
async def create_pull_request(task_id: str):
    """Create a pull request for the task"""
    task = get_storage().get_task(task_id)
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

    # Check if PR already exists for this branch
    try:
        existing_pr = subprocess.run(
            ["gh", "pr", "view", task.branch_name, "--json", "url,number"],
            capture_output=True,
            text=True
        )

        if existing_pr.returncode == 0 and existing_pr.stdout.strip():
            # PR already exists - update task with existing PR info
            import json as json_module
            pr_data = json_module.loads(existing_pr.stdout.strip())
            pr_url = pr_data.get("url")
            pr_number = pr_data.get("number")

            task.pr_url = pr_url
            task.pr_number = pr_number
            task.status = TaskStatus.HUMAN_REVIEW
            task.updated_at = datetime.now()
            get_storage().update_task(task)

            return {"message": "PR already exists - linked to task", "pr_url": pr_url, "task": task}
    except Exception:
        pass  # No existing PR, continue to create one

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

        # Extract PR number from URL
        import re
        pr_match = re.search(r'/pull/(\d+)', pr_url)
        if pr_match:
            task.pr_number = int(pr_match.group(1))

        # Stay in HUMAN_REVIEW to allow viewing PR reviews (CodeRabbit, etc)
        # Task moves to DONE when PR is merged or manually moved
        task.status = TaskStatus.HUMAN_REVIEW
        task.updated_at = datetime.now()
        get_storage().update_task(task)

        return {"message": "PR created - check PR Review tab for bot comments", "pr_url": pr_url, "task": task}

    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="GitHub CLI (gh) is not installed")
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        raise HTTPException(status_code=500, detail=f"Failed to create PR: {error_msg}")


@router.post("/tasks/{task_id}/sync-pr")
async def sync_pr_info(task_id: str):
    """
    Sync PR info from GitHub for a task.

    If the task has a branch and a PR exists on GitHub, updates the task with PR info.
    Useful when PR was created outside of Codeflow or pr_url wasn't saved properly.
    """
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task.branch_name:
        return {"synced": False, "message": "Task has no branch"}

    # Already has PR info
    if task.pr_url and task.pr_number:
        return {"synced": False, "message": "PR info already present", "pr_url": task.pr_url}

    try:
        result = subprocess.run(
            ["gh", "pr", "view", task.branch_name, "--json", "url,number,state"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0 and result.stdout.strip():
            import json as json_module
            pr_data = json_module.loads(result.stdout.strip())
            pr_url = pr_data.get("url")
            pr_number = pr_data.get("number")
            pr_state = pr_data.get("state")

            task.pr_url = pr_url
            task.pr_number = pr_number

            # If PR is merged, update task status
            if pr_state == "MERGED":
                task.pr_merged = True
                task.status = TaskStatus.DONE

            task.updated_at = datetime.now()
            get_storage().update_task(task)

            return {
                "synced": True,
                "message": "PR info synced from GitHub",
                "pr_url": pr_url,
                "pr_number": pr_number,
                "pr_state": pr_state
            }
        else:
            return {"synced": False, "message": "No PR found for this branch"}

    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="GitHub CLI (gh) is not installed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync PR info: {str(e)}")


@router.get("/tasks/{task_id}/check-conflicts")
async def check_conflicts(task_id: str):
    """Check if task branch has conflicts with develop"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task.worktree_path:
        raise HTTPException(status_code=400, detail="Task has no worktree")

    from backend.services.git_service import check_conflicts_with_develop

    result = await check_conflicts_with_develop(task.worktree_path)
    return result


@router.get("/tasks/{task_id}/pr-reviews")
async def get_pr_reviews(task_id: str):
    """Get PR review comments for a task"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task.pr_number:
        raise HTTPException(status_code=400, detail="Task has no PR")

    from backend.services.github_service import get_all_pr_reviews

    result = await get_all_pr_reviews(task.pr_number, settings.project_path)
    return result


@router.post("/tasks/{task_id}/fix-comments")
async def fix_comments(task_id: str, request: FixCommentsRequest):
    """Fix selected PR review comments using Claude"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task.pr_number:
        raise HTTPException(status_code=400, detail="Task has no PR")

    if not task.worktree_path:
        raise HTTPException(status_code=400, detail="Task has no worktree")

    if not request.comment_ids:
        raise HTTPException(status_code=400, detail="No comment IDs provided")

    from backend.services.pr_fixer import fix_pr_comments

    async def log_handler(message: str):
        await manager.send_log(task_id, message)

    result = await fix_pr_comments(
        task_id=task_id,
        comment_ids=request.comment_ids,
        pr_number=task.pr_number,
        worktree_path=task.worktree_path,
        project_path=settings.project_path,
        log_callback=log_handler
    )

    return result


@router.post("/tasks/{task_id}/resolve-conflicts")
async def resolve_conflicts(task_id: str):
    """Resolve merge conflicts with develop using Claude"""
    task = get_storage().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task.worktree_path:
        raise HTTPException(status_code=400, detail="Task has no worktree")

    from backend.services.conflict_resolver import resolve_conflicts as do_resolve_conflicts

    async def log_handler(message: str):
        await manager.send_log(task_id, message)

    result = await do_resolve_conflicts(
        task_id=task_id,
        worktree_path=task.worktree_path,
        log_callback=log_handler
    )

    return result
