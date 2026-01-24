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

## Instructions

Break this task into 3-7 subtasks. Each subtask should:
1. Be completable in one coding session (15-30 min)
2. Have a clear, specific scope
3. Be independently testable when possible
4. Follow a logical order (dependencies respected)

## Output Format

Return ONLY a JSON array with this structure:

[
  {{
    "id": "subtask-1",
    "title": "Short descriptive title",
    "description": "Detailed description of what to implement",
    "order": 1,
    "dependencies": []
  }},
  {{
    "id": "subtask-2",
    "title": "Another subtask",
    "description": "Description with specific details",
    "order": 2,
    "dependencies": ["subtask-1"]
  }}
]

Rules:
- IDs must be "subtask-1", "subtask-2", etc.
- Order starts at 1
- Dependencies reference IDs of subtasks that must complete first
- Be specific in descriptions, mention file names and functions when relevant
- Return ONLY the JSON array, nothing else
'''


async def generate_subtasks(
    task: Task,
    project_path: str,
    on_output: Callable[[str], None] | None = None
) -> list[Subtask]:
    """
    Generate subtasks for a task using Claude Code CLI.

    Args:
        task: The task to break down
        project_path: Project path
        on_output: Callback for streaming

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

    # Build the prompt
    prompt = PLANNING_PROMPT.format(
        project_context=project_context,
        task_title=task.title,
        task_description=task.description or task.title,
        file_references=file_refs_str
    )

    logger.info(f"Generating subtasks for task {task.id}: {task.title}")

    # Call Claude CLI
    success, result = await run_claude_for_json(
        prompt=prompt,
        cwd=project_path,
        timeout=300,  # 5 min max for planning
        on_output=on_output
    )

    if not success or result is None:
        logger.error(f"Failed to generate subtasks for task {task.id}")
        # Return a single fallback subtask
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

    # Parse into list of Subtask
    subtasks = parse_subtasks_response(result)

    logger.info(f"Generated {len(subtasks)} subtasks for task {task.id}")

    return subtasks


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
