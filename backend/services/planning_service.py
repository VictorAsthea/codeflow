"""
Service for the Planning phase.
Generates subtasks from the task description.
Uses Claude Code CLI (subscription), not the paid API.
"""

import logging
from typing import Callable
from datetime import datetime

from backend.models import Task, Subtask, SubtaskStatus
from backend.services.project_context import get_project_context
from backend.services.claude_cli import run_claude_for_json

logger = logging.getLogger(__name__)


PLANNING_PROMPT = '''You are a senior developer planning the implementation of a feature.

## Project Context
{project_context}

## Task to Implement
Title: {task_title}
Description: {task_description}

{file_references}

{screenshots_section}

## Your Mission

1. FIRST: Read and analyze the task description carefully to understand what needs to be built
2. THEN: Explore relevant files in the codebase if needed to understand the existing architecture
3. FINALLY: Break this task into 3-7 concrete subtasks

Each subtask should:
- Be completable in one coding session (15-30 min)
- Have a clear, specific scope with exact files to create/modify
- Follow a logical order (dependencies respected)

## CRITICAL: Output Format

After your analysis, your FINAL output must be ONLY a valid JSON array. No text before or after.

Example format:
[
  {{
    "id": "subtask-1",
    "title": "Create the backend endpoint for X",
    "description": "Create POST /api/x endpoint in backend/routers/x.py that handles...",
    "order": 1,
    "dependencies": []
  }},
  {{
    "id": "subtask-2",
    "title": "Add frontend component for X",
    "description": "Create frontend/js/x.js with the component that calls the API...",
    "order": 2,
    "dependencies": ["subtask-1"]
  }}
]

Rules:
- IDs: "subtask-1", "subtask-2", etc.
- Order: starts at 1
- Dependencies: array of subtask IDs that must complete first
- Descriptions: Be specific! Mention exact file paths and function names
- Output: Return ONLY the JSON array as your final response
'''


async def generate_subtasks(
    task: Task,
    project_path: str,
    on_output: Callable[[str], None] | None = None,
    max_retries: int = 2
) -> list[Subtask]:
    """
    Generate subtasks for a task using Claude Code CLI.

    Args:
        task: The task to break down
        project_path: Project path
        on_output: Callback for streaming
        max_retries: Number of retries on failure

    Returns:
        List of Subtask
    """
    # Load project context
    ctx = get_project_context(project_path)
    project_context = ctx.get_context_for_prompt()

    # Format file references if any
    file_refs_str = ""
    if task.file_references:
        refs = []
        for ref in task.file_references:
            if ref.line_start and ref.line_end:
                refs.append(f"- {ref.path} (lines {ref.line_start}-{ref.line_end})")
            else:
                refs.append(f"- {ref.path}")
        file_refs_str = "## Referenced Files\n" + "\n".join(refs)

    # Format screenshots if any
    screenshots_str = ""
    if task.screenshots:
        screenshots_str = "## Screenshots\nThe following screenshots are provided to help understand the visual context of the task:\n"
        for i, screenshot in enumerate(task.screenshots, 1):
            screenshots_str += f"\n[Screenshot {i}]\n{screenshot}\n"

    # Build the prompt
    prompt = PLANNING_PROMPT.format(
        project_context=project_context,
        task_title=task.title,
        task_description=task.description or task.title,
        file_references=file_refs_str,
        screenshots_section=screenshots_str
    )

    logger.info(f"Generating subtasks for task {task.id}: {task.title}")

    # Retry loop for robustness
    last_error = None
    for attempt in range(max_retries + 1):
        if attempt > 0:
            logger.info(f"Retry attempt {attempt}/{max_retries} for subtask generation")
            if on_output:
                on_output(f"\n[Planning] Retry attempt {attempt}/{max_retries}...\n")

        # Call Claude CLI (with retry support)
        success, result, retry_metadata = await run_claude_for_json(
            prompt=prompt,
            cwd=project_path,
            timeout=300,  # 5 min max for planning
            on_output=on_output,
            task_id=f"{task.id}:planning",  # Task ID for metrics tracking
        )

        if retry_metadata and retry_metadata.had_retries:
            logger.info(
                f"Planning completed after {retry_metadata.total_attempts} attempts "
                f"(retry time: {retry_metadata.total_retry_time:.1f}s)"
            )

        if success and result is not None:
            # Parse into list of Subtask
            subtasks = parse_subtasks_response(result)

            if len(subtasks) > 1:
                # Success - got multiple subtasks
                logger.info(f"Generated {len(subtasks)} subtasks for task {task.id}")
                return subtasks
            elif len(subtasks) == 1:
                # Got single subtask - might be valid for simple tasks
                logger.info(f"Generated 1 subtask for task {task.id}")
                return subtasks
            else:
                last_error = "Empty subtasks list returned"
                logger.warning(f"Attempt {attempt + 1}: {last_error}")
        else:
            last_error = "Claude CLI returned failure or None"
            logger.warning(f"Attempt {attempt + 1}: {last_error}")

    # All retries exhausted - return fallback
    logger.error(f"Failed to generate subtasks for task {task.id} after {max_retries + 1} attempts: {last_error}")
    if on_output:
        on_output(f"\n[Planning] WARNING: Could not generate detailed subtasks. Using single-task fallback.\n")

    return [
        Subtask(
            id="subtask-1",
            title=f"Implement: {task.title}",
            description=task.description or "Complete the task as described",
            order=1,
            dependencies=[],
            status=SubtaskStatus.PENDING
        )
    ]


def parse_subtasks_response(data: any) -> list[Subtask]:
    """Parse the JSON response into a list of Subtask."""

    # If it's a list directly
    if isinstance(data, list):
        items = data
    # If it's a dict with a "subtasks" key
    elif isinstance(data, dict) and "subtasks" in data:
        items = data["subtasks"]
    else:
        logger.warning(f"Unexpected response format: {type(data)}")
        return []

    subtasks = []
    for i, item in enumerate(items):
        try:
            subtask = Subtask(
                id=item.get("id", f"subtask-{i+1}"),
                title=item.get("title", "Untitled subtask"),
                description=item.get("description"),
                order=item.get("order", i + 1),
                dependencies=item.get("dependencies", []),
                status=SubtaskStatus.PENDING
            )
            subtasks.append(subtask)
        except Exception as e:
            logger.error(f"Failed to parse subtask: {e}")
            continue

    # Sort by order
    subtasks.sort(key=lambda s: s.order)

    return subtasks


def validate_subtasks(subtasks: list[Subtask]) -> bool:
    """Validate that subtasks have valid dependencies."""
    ids = {s.id for s in subtasks}

    for subtask in subtasks:
        for dep_id in subtask.dependencies:
            if dep_id not in ids:
                logger.warning(f"Subtask {subtask.id} has invalid dependency: {dep_id}")
                return False

    return True


def get_subtask_by_id(subtasks: list[Subtask], subtask_id: str) -> Subtask | None:
    """Get a subtask by its ID."""
    for subtask in subtasks:
        if subtask.id == subtask_id:
            return subtask
    return None
