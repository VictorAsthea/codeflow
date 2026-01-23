"""
Task orchestrator for handling AI review workflow
"""
import logging
from datetime import datetime
from typing import Callable, Any
from backend.models import Task, TaskStatus
from backend.config import settings
from backend.services.code_reviewer import (
    run_code_review,
    format_issues_for_context
)
from backend.services.phase_executor import execute_all_phases

logger = logging.getLogger(__name__)


def get_storage():
    """Get storage instance (lazy import to avoid circular dependency)"""
    from backend.main import storage
    return storage


async def update_task(task: Task):
    """Update task in storage"""
    get_storage().update_task(task)


async def handle_ai_review(
    task: Task,
    log_callback: Callable[[str], Any] = None
) -> dict:
    """
    Handle automatic AI code review after coding phase

    Args:
        task: The task to review
        log_callback: Optional callback for streaming logs

    Returns:
        dict with review result and next action
    """
    if not task.worktree_path:
        return {
            "success": False,
            "error": "No worktree path found for task"
        }

    if log_callback:
        await log_callback("\n=== Starting AI Code Review ===\n")

    task.review_status = "in_progress"
    await update_task(task)

    # Run code review
    review_result = await run_code_review(
        worktree_path=task.worktree_path,
        timeout=settings.code_review_timeout
    )

    print(f"[AI_REVIEW] review_result.success: {review_result.success}")
    print(f"[AI_REVIEW] review_result.error_message: {review_result.error_message}")
    print(f"[AI_REVIEW] issues count: {len(review_result.issues)}")

    # Store the review output for display
    task.review_output = review_result.raw_output

    if not review_result.success:
        # Review failed - fallback to human review
        if log_callback:
            await log_callback(f"Code review failed: {review_result.error_message}\n")
            await log_callback("Falling back to human review\n")

        task.status = TaskStatus.HUMAN_REVIEW
        task.review_status = "failed"
        await update_task(task)

        return {
            "success": False,
            "action": "human_review",
            "error": review_result.error_message
        }

    # Check for high-confidence issues
    high_confidence_issues = review_result.get_high_confidence_issues(
        threshold=settings.code_review_confidence_threshold
    )

    if log_callback:
        await log_callback(f"Review completed: {review_result.summary()}\n")
        if high_confidence_issues:
            await log_callback(f"Found {len(high_confidence_issues)} high-confidence issue(s)\n")

    # Store all issues
    task.review_issues = [issue.to_dict() for issue in review_result.issues]

    if not high_confidence_issues:
        # No critical issues - proceed to human review
        if log_callback:
            await log_callback("No critical issues found - proceeding to human review\n")

        task.status = TaskStatus.HUMAN_REVIEW
        task.review_status = "completed"
        await update_task(task)

        return {
            "success": True,
            "action": "human_review",
            "issues": task.review_issues
        }

    # Critical issues found - check if auto-fix is enabled
    if not settings.code_review_auto_fix:
        if log_callback:
            await log_callback("Auto-fix disabled - proceeding to human review\n")

        task.status = TaskStatus.AI_REVIEW
        task.review_status = "completed"
        await update_task(task)

        return {
            "success": True,
            "action": "manual_review",
            "issues": task.review_issues
        }

    # Check if max cycles reached
    if task.review_cycles >= settings.code_review_max_cycles:
        if log_callback:
            await log_callback(f"Max review cycles ({settings.code_review_max_cycles}) reached - proceeding to human review\n")

        task.status = TaskStatus.AI_REVIEW
        task.review_status = "max_cycles_reached"
        await update_task(task)

        return {
            "success": True,
            "action": "max_cycles",
            "issues": task.review_issues
        }

    # Auto-fix enabled and cycles remaining - retry with context
    if log_callback:
        await log_callback(f"\n=== Auto-fixing issues (cycle {task.review_cycles + 1}/{settings.code_review_max_cycles}) ===\n")

    task.review_cycles += 1
    task.review_status = "retrying"
    await update_task(task)

    # Format issues as context for coding phase
    review_context = format_issues_for_context(high_confidence_issues)

    # Re-run coding phase with review context
    result = await execute_all_phases(
        task,
        task.worktree_path,
        log_callback,
        review_context=review_context
    )

    if result["success"]:
        # Coding succeeded - run review again
        if log_callback:
            await log_callback("\n=== Re-running code review after fixes ===\n")

        # Recursively handle review again
        return await handle_ai_review(task, log_callback)
    else:
        # Coding failed - mark for human review
        if log_callback:
            await log_callback("\n=== Auto-fix failed - proceeding to human review ===\n")

        task.status = TaskStatus.AI_REVIEW
        task.review_status = "auto_fix_failed"
        await update_task(task)

        return {
            "success": False,
            "action": "auto_fix_failed",
            "issues": task.review_issues
        }


async def retry_with_review_fixes(
    task: Task,
    log_callback: Callable[[str], Any] = None
) -> dict:
    """
    Manually trigger retry with review fixes

    Args:
        task: The task to retry
        log_callback: Optional callback for streaming logs

    Returns:
        dict with retry result
    """
    if not task.review_issues:
        return {
            "success": False,
            "error": "No review issues found"
        }

    if task.review_cycles >= settings.code_review_max_cycles:
        return {
            "success": False,
            "error": f"Max review cycles ({settings.code_review_max_cycles}) already reached"
        }

    if log_callback:
        await log_callback(f"\n=== Manual retry with fixes (cycle {task.review_cycles + 1}/{settings.code_review_max_cycles}) ===\n")

    task.review_cycles += 1
    task.status = TaskStatus.IN_PROGRESS
    task.review_status = "retrying"
    await update_task(task)

    # Parse issues from stored dict format
    from backend.services.code_reviewer import ReviewIssue, ReviewSeverity
    issues = []
    for issue_dict in task.review_issues:
        issues.append(ReviewIssue(
            severity=ReviewSeverity(issue_dict["severity"]),
            confidence=issue_dict["confidence"],
            message=issue_dict["message"],
            file_path=issue_dict.get("file_path"),
            line_number=issue_dict.get("line_number")
        ))

    review_context = format_issues_for_context(issues)

    # Re-run coding phase
    result = await execute_all_phases(
        task,
        task.worktree_path,
        log_callback,
        review_context=review_context
    )

    if result["success"]:
        # Run review again
        return await handle_ai_review(task, log_callback)
    else:
        task.status = TaskStatus.AI_REVIEW
        task.review_status = "auto_fix_failed"
        await update_task(task)

        return {
            "success": False,
            "error": "Coding phase failed during retry"
        }
