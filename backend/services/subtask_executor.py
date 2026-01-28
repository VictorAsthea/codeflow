"""
Service to execute individual subtasks with Claude Code CLI.
Each subtask runs with fresh context for clean, focused implementation.
"""

import logging
from datetime import datetime
from typing import Callable

from backend.models import Task, Subtask, SubtaskStatus
from backend.services.project_context import get_project_context
from backend.services.claude_cli import run_claude_for_coding

logger = logging.getLogger(__name__)


SUBTASK_PROMPT_TEMPLATE = '''## Context

You are implementing subtask {subtask_order} of {total_subtasks} for this task.

### Project
{project_context}

### Task
Title: {task_title}
Description: {task_description}

{task_screenshots}

### Your Subtask
ID: {subtask_id}
Title: {subtask_title}
Description: {subtask_description}

### Previously Completed Subtasks
{completed_subtasks}

### Remaining Subtasks (DO NOT implement these)
{remaining_subtasks}

## Instructions

1. Implement ONLY this subtask - do not work on other subtasks
2. Follow existing code patterns and conventions
3. Write clean, maintainable code
4. Add comments where helpful
5. Test your changes if possible

Focus on this subtask only. Other subtasks will be handled separately.
'''


async def execute_subtask(
    task: Task,
    subtask: Subtask,
    project_path: str,
    worktree_path: str,
    on_output: Callable[[str], None] | None = None
) -> bool:
    """
    Execute a subtask with Claude Code CLI.

    Args:
        task: The parent task
        subtask: The subtask to execute
        project_path: Main project path (for context)
        worktree_path: Worktree path where to execute
        on_output: Callback to stream output

    Returns:
        True if success, False if failure
    """
    # Mark as in_progress
    subtask.status = SubtaskStatus.IN_PROGRESS
    subtask.started_at = datetime.now()

    logger.info(f"Executing subtask {subtask.id}: {subtask.title}")

    # Build the prompt
    prompt = build_subtask_prompt(task, subtask, project_path)

    try:
        # Execute Claude Code CLI (with retry support)
        success, retry_metadata = await run_claude_for_coding(
            prompt=prompt,
            cwd=worktree_path,
            timeout=600,  # 10 min max per subtask
            on_output=on_output,
            task_id=f"{task.id}:{subtask.id}",  # Task:subtask ID for metrics tracking
        )

        if success:
            subtask.status = SubtaskStatus.COMPLETED
            subtask.completed_at = datetime.now()
            if retry_metadata and retry_metadata.had_retries:
                logger.info(
                    f"Subtask {subtask.id} completed successfully after "
                    f"{retry_metadata.total_attempts} attempts"
                )
            else:
                logger.info(f"Subtask {subtask.id} completed successfully")
        else:
            subtask.status = SubtaskStatus.FAILED
            error_msg = "Claude Code CLI execution failed"
            if retry_metadata and retry_metadata.errors:
                last_error = retry_metadata.errors[-1]
                error_msg = f"{error_msg}: {last_error.get('error_type', 'unknown')}"
            subtask.error = error_msg
            logger.error(f"Subtask {subtask.id} failed")

        return success

    except Exception as e:
        subtask.status = SubtaskStatus.FAILED
        subtask.error = str(e)
        logger.error(f"Subtask {subtask.id} error: {e}")
        return False


def build_subtask_prompt(task: Task, subtask: Subtask, project_path: str) -> str:
    """Build the prompt for a subtask."""

    # Project context
    ctx = get_project_context(project_path)
    project_context = ctx.get_context_for_prompt()

    # Completed subtasks
    completed = [s for s in task.subtasks if s.status == SubtaskStatus.COMPLETED]
    completed_str = "\n".join([f"- [DONE] {s.title}" for s in completed]) or "None yet"

    # Remaining subtasks (after this one)
    remaining = [s for s in task.subtasks
                 if s.status == SubtaskStatus.PENDING and s.id != subtask.id]
    remaining_str = "\n".join([f"- {s.title}" for s in remaining]) or "None"

    # Format screenshots if any
    screenshots_str = ""
    if task.screenshots:
        screenshots_str = "### Screenshots\nThe following screenshots show the visual context for this task:\n"
        for i, screenshot in enumerate(task.screenshots, 1):
            screenshots_str += f"\n[Screenshot {i}]\n{screenshot}\n"

    return SUBTASK_PROMPT_TEMPLATE.format(
        subtask_order=subtask.order,
        total_subtasks=len(task.subtasks),
        project_context=project_context,
        task_title=task.title,
        task_description=task.description or "",
        task_screenshots=screenshots_str,
        subtask_id=subtask.id,
        subtask_title=subtask.title,
        subtask_description=subtask.description or "",
        completed_subtasks=completed_str,
        remaining_subtasks=remaining_str
    )


def get_next_subtask(task: Task) -> Subtask | None:
    """
    Get the next subtask to execute.
    Respects dependencies.
    """
    completed_ids = {s.id for s in task.subtasks if s.status == SubtaskStatus.COMPLETED}

    for subtask in sorted(task.subtasks, key=lambda s: s.order):
        if subtask.status != SubtaskStatus.PENDING:
            continue

        # Check that all dependencies are completed
        deps_met = all(dep_id in completed_ids for dep_id in subtask.dependencies)
        if deps_met:
            return subtask

    return None


def all_subtasks_completed(task: Task) -> bool:
    """Check if all subtasks are completed."""
    if not task.subtasks:
        return False
    return all(s.status == SubtaskStatus.COMPLETED for s in task.subtasks)


def any_subtask_failed(task: Task) -> bool:
    """Check if any subtask has failed."""
    return any(s.status == SubtaskStatus.FAILED for s in task.subtasks)


def get_failed_subtasks(task: Task) -> list[Subtask]:
    """Get all failed subtasks."""
    return [s for s in task.subtasks if s.status == SubtaskStatus.FAILED]


def get_subtask_progress(task: Task) -> dict:
    """Get subtask progress stats."""
    total = len(task.subtasks)
    if total == 0:
        return {
            "total": 0,
            "completed": 0,
            "in_progress": 0,
            "pending": 0,
            "failed": 0,
            "percentage": 0
        }

    completed = sum(1 for s in task.subtasks if s.status == SubtaskStatus.COMPLETED)
    in_progress = sum(1 for s in task.subtasks if s.status == SubtaskStatus.IN_PROGRESS)
    failed = sum(1 for s in task.subtasks if s.status == SubtaskStatus.FAILED)

    return {
        "total": total,
        "completed": completed,
        "in_progress": in_progress,
        "pending": total - completed - in_progress - failed,
        "failed": failed,
        "percentage": int((completed / total) * 100) if total > 0 else 0
    }


def reset_subtask(subtask: Subtask):
    """Reset a subtask to pending state (for retry)."""
    subtask.status = SubtaskStatus.PENDING
    subtask.started_at = None
    subtask.completed_at = None
    subtask.error = None


def reset_failed_subtasks(task: Task):
    """Reset all failed subtasks to pending (for retry)."""
    for subtask in task.subtasks:
        if subtask.status == SubtaskStatus.FAILED:
            reset_subtask(subtask)
