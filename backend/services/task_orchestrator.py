"""
Main task orchestrator for the v0.4 workflow.
Manages the 3 phases: Planning -> Coding -> Validation
Uses exclusively Claude Code CLI (subscription).
"""

import asyncio
import logging
from datetime import datetime
from typing import Callable, Any

from backend.models import (
    Task, TaskStatus, Subtask, SubtaskStatus,
    Phase, PhaseStatus, PhaseConfig, PhaseMetrics
)
from backend.config import settings
from backend.services.planning_service import generate_subtasks
from backend.services.subtask_executor import (
    execute_subtask,
    get_next_subtask,
    all_subtasks_completed,
    any_subtask_failed,
    get_failed_subtasks,
    get_subtask_progress,
    reset_failed_subtasks
)
from backend.services.validation_service import (
    run_validation,
    auto_fix_issues,
    should_auto_fix
)
from backend.services.git_service import commit_changes, push_branch

logger = logging.getLogger(__name__)


def get_parallel_manager():
    """Get parallel manager instance (lazy import to avoid circular dependency)"""
    from backend.websocket_manager import parallel_manager
    return parallel_manager


def get_storage():
    """Get storage instance (lazy import to avoid circular dependency)"""
    from backend.main import storage
    return storage


async def update_task(task: Task):
    """Update task in storage"""
    task.updated_at = datetime.now()
    get_storage().update_task(task)


class TaskOrchestrator:
    """Orchestrates the complete workflow of a task."""

    def __init__(
        self,
        task: Task,
        project_path: str,
        worktree_path: str,
        emit_event: Callable[[str, dict], Any] | None = None,
        log_callback: Callable[[str], Any] | None = None
    ):
        self.task = task
        self.project_path = project_path
        self.worktree_path = worktree_path
        self._original_emit = emit_event or (lambda event, data: None)
        self.log_callback = log_callback

        # Initialize phases if needed
        self._ensure_phases()

    def emit(self, event: str, data: dict):
        """
        Emit an event to both the original callback and the parallel manager.
        This ensures all parallel execution clients receive real-time updates.
        """
        # Call original emit callback
        self._original_emit(event, data)

        # Notify parallel manager asynchronously
        asyncio.create_task(self._notify_parallel_manager(event, data))

    async def _notify_parallel_manager(self, event: str, data: dict):
        """Notify the parallel execution manager about task events."""
        try:
            pm = get_parallel_manager()

            if event == "phase:started":
                await pm.notify_phase_changed(
                    task_id=data.get("task_id"),
                    phase=data.get("phase"),
                    metrics={}
                )
            elif event == "phase:completed":
                await pm.notify_phase_changed(
                    task_id=data.get("task_id"),
                    phase=data.get("phase"),
                    metrics=data.get("result", {})
                )
            elif event == "subtask:started":
                subtask = data.get("subtask", {})
                await pm.notify_subtask_progress(
                    task_id=data.get("task_id"),
                    subtask_info=subtask,
                    progress={"percentage": 0, "status": "started"}
                )
            elif event == "subtask:completed":
                subtask = data.get("subtask", {})
                progress = data.get("progress", {})
                await pm.notify_subtask_progress(
                    task_id=data.get("task_id"),
                    subtask_info=subtask,
                    progress=progress
                )
            elif event == "subtask:failed":
                subtask = data.get("subtask", {})
                await pm.notify_subtask_progress(
                    task_id=data.get("task_id"),
                    subtask_info=subtask,
                    progress={"percentage": 0, "status": "failed", "error": data.get("error")}
                )
            elif event == "task:failed":
                await pm.notify_task_failed(
                    task_id=data.get("task_id"),
                    error=data.get("error")
                )
            elif event == "task:status_changed":
                pm.update_task_progress(data.get("task_id"), {
                    "status": data.get("status")
                })
                await pm.broadcast_queue_update("task_status_changed", data)
            elif event == "subtasks:generated":
                pm.update_task_progress(data.get("task_id"), {
                    "total_subtasks": len(data.get("subtasks", []))
                })
                await pm.broadcast_queue_update("subtasks_generated", {
                    "task_id": data.get("task_id"),
                    "count": len(data.get("subtasks", []))
                })
        except Exception as e:
            logger.warning(f"Failed to notify parallel manager: {e}")

    def _ensure_phases(self):
        """Ensure task has all phase objects initialized."""
        if "planning" not in self.task.phases:
            self.task.phases["planning"] = Phase(
                name="planning",
                config=PhaseConfig(model=settings.planning_model)
            )
        if "coding" not in self.task.phases:
            self.task.phases["coding"] = Phase(
                name="coding",
                config=PhaseConfig(model=settings.coding_model)
            )
        if "validation" not in self.task.phases:
            self.task.phases["validation"] = Phase(
                name="validation",
                config=PhaseConfig(model=settings.validation_model)
            )

    async def log(self, message: str, phase: str | None = None):
        """Log message to callback and phase logs."""
        if self.log_callback:
            try:
                result = self.log_callback(message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Log callback error: {e}")

        if phase and phase in self.task.phases:
            self.task.phases[phase].logs.append(message.rstrip())

    async def run(self) -> dict:
        """Execute the full workflow (Planning + Coding + Validation)."""
        # Register task with parallel manager at start
        try:
            pm = get_parallel_manager()
            await pm.notify_task_started(self.task.id, {
                "title": self.task.title,
                "worktree_path": self.worktree_path,
                "current_phase": "planning",
                "status": "running"
            })
        except Exception as e:
            logger.warning(f"Failed to register task with parallel manager: {e}")

        try:
            # Phase 1: Planning
            await self.run_planning_phase()

            # Phase 2: Coding
            await self.run_coding_phase()

            # Phase 3: Validation (automatic after coding)
            await self.run_validation_phase()

            # Notify parallel manager of completion
            try:
                pm = get_parallel_manager()
                await pm.notify_task_completed(self.task.id, {"status": "completed"})
            except Exception as e:
                logger.warning(f"Failed to notify parallel manager of completion: {e}")

            return {"success": True}

        except Exception as e:
            logger.error(f"Task {self.task.id} failed: {e}")
            await self.log(f"ERROR: {str(e)}\n", self.task.current_phase)

            self.emit("task:failed", {
                "task_id": self.task.id,
                "error": str(e)
            })

            return {"success": False, "error": str(e)}

    async def run_planning_phase(self):
        """Phase 1: Generate subtasks via Claude CLI."""
        phase = self.task.phases["planning"]
        phase.status = PhaseStatus.RUNNING
        phase.started_at = datetime.now()
        self.task.current_phase = "planning"

        await update_task(self.task)

        self.emit("phase:started", {
            "task_id": self.task.id,
            "phase": "planning"
        })

        await self.log("\n=== PHASE 1: PLANNING ===\n", "planning")
        await self.log("Analyzing task and generating subtasks...\n", "planning")

        # Generate subtasks via Claude CLI
        subtasks = await generate_subtasks(
            task=self.task,
            project_path=self.project_path,
            on_output=lambda line: asyncio.create_task(
                self.log(line, "planning")
            )
        )

        self.task.subtasks = subtasks

        await self.log(f"\nGenerated {len(subtasks)} subtasks:\n", "planning")
        for s in subtasks:
            await self.log(f"  {s.order}. {s.title}\n", "planning")

        # Emit the subtasks
        self.emit("subtasks:generated", {
            "task_id": self.task.id,
            "subtasks": [s.model_dump() for s in subtasks]
        })

        phase.status = PhaseStatus.DONE
        phase.completed_at = datetime.now()
        phase.metrics.progress_percentage = 100

        await update_task(self.task)

        self.emit("phase:completed", {
            "task_id": self.task.id,
            "phase": "planning"
        })

        await self.log("\nPlanning phase completed.\n", "planning")

    async def run_coding_phase(self):
        """Phase 2: Execute each subtask via Claude CLI."""
        phase = self.task.phases["coding"]
        phase.status = PhaseStatus.RUNNING
        phase.started_at = datetime.now()
        self.task.current_phase = "coding"

        await update_task(self.task)

        self.emit("phase:started", {
            "task_id": self.task.id,
            "phase": "coding"
        })

        await self.log("\n=== PHASE 2: CODING ===\n", "coding")

        # Loop through subtasks
        while True:
            subtask = get_next_subtask(self.task)

            if subtask is None:
                if all_subtasks_completed(self.task):
                    break
                elif any_subtask_failed(self.task):
                    failed = get_failed_subtasks(self.task)
                    raise Exception(f"Subtasks failed: {[s.title for s in failed]}")
                else:
                    # No available subtask (blocked by dependencies)
                    await asyncio.sleep(1)
                    continue

            self.task.current_subtask_id = subtask.id
            await update_task(self.task)

            # Update phase metrics
            progress = get_subtask_progress(self.task)
            phase.metrics.progress_percentage = progress["percentage"]
            phase.metrics.current_turn = progress["completed"]
            phase.metrics.estimated_turns = progress["total"]

            await self.log(f"\n--- Subtask {subtask.order}/{len(self.task.subtasks)}: {subtask.title} ---\n", "coding")

            self.emit("subtask:started", {
                "task_id": self.task.id,
                "subtask": subtask.model_dump()
            })

            # Execute the subtask via Claude CLI
            success = await execute_subtask(
                task=self.task,
                subtask=subtask,
                project_path=self.project_path,
                worktree_path=self.worktree_path,
                on_output=lambda line: asyncio.create_task(
                    self.log(line, "coding")
                )
            )

            await update_task(self.task)

            if success:
                await self.log(f"\nSubtask {subtask.order} completed successfully.\n", "coding")

                self.emit("subtask:completed", {
                    "task_id": self.task.id,
                    "subtask": subtask.model_dump(),
                    "progress": get_subtask_progress(self.task)
                })
            else:
                await self.log(f"\nSubtask {subtask.order} FAILED: {subtask.error}\n", "coding")

                self.emit("subtask:failed", {
                    "task_id": self.task.id,
                    "subtask": subtask.model_dump(),
                    "error": subtask.error
                })

                raise Exception(f"Subtask failed: {subtask.title}")

        phase.status = PhaseStatus.DONE
        phase.completed_at = datetime.now()
        phase.metrics.progress_percentage = 100
        self.task.current_subtask_id = None

        await update_task(self.task)

        self.emit("phase:completed", {
            "task_id": self.task.id,
            "phase": "coding"
        })

        await self.log("\nCoding phase completed.\n", "coding")

        # Commit all changes
        await self.log("Committing changes...\n", "coding")
        commit_message = f"feat: {self.task.title}\n\nTask ID: {self.task.id}"
        commit_result = await commit_changes(self.worktree_path, commit_message)

        if commit_result.get("success"):
            if commit_result.get("commit_sha"):
                await self.log(f"Committed: {commit_result['commit_sha'][:8]}\n", "coding")
            else:
                await self.log("No changes to commit.\n", "coding")
        else:
            await self.log(f"Commit failed: {commit_result.get('error', 'Unknown error')}\n", "coding")

        # Push to remote
        await self.log("Pushing to remote...\n", "coding")
        push_result = await push_branch(self.worktree_path)

        if push_result.get("success"):
            await self.log("Pushed to remote.\n", "coding")
        else:
            await self.log(f"Push failed: {push_result.get('error', 'Unknown error')}\n", "coding")

        await self.log("Moving to AI Review.\n", "coding")

        # Auto-move to "AI Review"
        self.task.status = TaskStatus.AI_REVIEW
        await update_task(self.task)

        self.emit("task:status_changed", {
            "task_id": self.task.id,
            "status": "ai_review"
        })

    async def run_validation_phase(self) -> dict:
        """
        Phase 3: Automatic QA via Claude CLI.
        Called separately when the task is in "AI Review" status.
        """
        phase = self.task.phases["validation"]
        phase.status = PhaseStatus.RUNNING
        phase.started_at = datetime.now()
        self.task.current_phase = "validation"

        await update_task(self.task)

        self.emit("phase:started", {
            "task_id": self.task.id,
            "phase": "validation"
        })

        await self.log("\n=== PHASE 3: VALIDATION ===\n", "validation")
        await self.log("Starting QA validation...\n", "validation")

        result = await run_validation(
            task=self.task,
            project_path=self.project_path,
            worktree_path=self.worktree_path,
            on_output=lambda line: asyncio.create_task(
                self.log(line, "validation")
            )
        )

        await self.log(f"\nQA Result: {'PASS' if result['passed'] else 'FAIL'}\n", "validation")

        # Store review output
        self.task.review_output = result.get("raw_output", "")
        self.task.review_issues = [
            {"message": issue, "severity": "medium", "confidence": 0.8}
            for issue in result.get("issues", [])
        ]

        if result["passed"]:
            phase.status = PhaseStatus.DONE
            phase.completed_at = datetime.now()
            phase.metrics.progress_percentage = 100

            self.task.status = TaskStatus.HUMAN_REVIEW
            self.task.review_status = "completed"
            await update_task(self.task)

            self.emit("task:status_changed", {
                "task_id": self.task.id,
                "status": "human_review"
            })

            await self.log("Validation PASSED - moving to Human Review.\n", "validation")

        else:
            await self.log(f"Issues found: {result['issues']}\n", "validation")

            # Check if we should auto-fix (only for minor issues)
            if should_auto_fix(result) and self.task.review_cycles < settings.code_review_max_cycles:
                await self.log("\nAttempting auto-fix...\n", "validation")
                self.task.review_cycles += 1

                fixed = await auto_fix_issues(
                    task=self.task,
                    issues=result["issues"],
                    worktree_path=self.worktree_path,
                    on_output=lambda line: asyncio.create_task(
                        self.log(line, "validation")
                    )
                )

                if fixed:
                    await self.log("Auto-fix completed. Re-running validation...\n", "validation")
                    # Recursively validate again
                    return await self.run_validation_phase()

            # Move to HUMAN_REVIEW with issues noted (user decides what to do)
            phase.status = PhaseStatus.DONE
            phase.completed_at = datetime.now()

            self.task.status = TaskStatus.HUMAN_REVIEW
            self.task.review_status = "needs_attention"
            await update_task(self.task)

            self.emit("task:status_changed", {
                "task_id": self.task.id,
                "status": "human_review"
            })

            await self.log("Validation completed with issues - moving to Human Review for decision.\n", "validation")

        self.emit("phase:completed", {
            "task_id": self.task.id,
            "phase": "validation",
            "result": result
        })

        return result


# Entry points

async def start_task(
    task: Task,
    project_path: str,
    worktree_path: str,
    emit_event: Callable[[str, dict], Any] | None = None,
    log_callback: Callable[[str], Any] | None = None
) -> dict:
    """Entry point to start a task (Planning + Coding)."""
    orchestrator = TaskOrchestrator(
        task=task,
        project_path=project_path,
        worktree_path=worktree_path,
        emit_event=emit_event,
        log_callback=log_callback
    )
    return await orchestrator.run()


async def start_validation(
    task: Task,
    project_path: str,
    worktree_path: str,
    emit_event: Callable[[str, dict], Any] | None = None,
    log_callback: Callable[[str], Any] | None = None
) -> dict:
    """Entry point for validation (when task moves to AI Review)."""
    orchestrator = TaskOrchestrator(
        task=task,
        project_path=project_path,
        worktree_path=worktree_path,
        emit_event=emit_event,
        log_callback=log_callback
    )
    return await orchestrator.run_validation_phase()


# Legacy function for backward compatibility
async def handle_ai_review(
    task: Task,
    log_callback: Callable[[str], Any] | None = None
) -> dict:
    """
    Handle automatic AI code review after coding phase.
    Legacy function - now uses validation phase.
    """
    if not task.worktree_path:
        return {
            "success": False,
            "error": "No worktree path found for task"
        }

    result = await start_validation(
        task=task,
        project_path=settings.project_path,
        worktree_path=task.worktree_path,
        log_callback=log_callback
    )

    return {
        "success": result.get("passed", False),
        "action": "human_review" if result.get("passed") else "needs_attention",
        "issues": task.review_issues
    }


async def retry_with_review_fixes(
    task: Task,
    log_callback: Callable[[str], Any] | None = None
) -> dict:
    """
    Manually trigger retry with review fixes.
    Legacy function for backward compatibility.
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

    # Reset failed subtasks if any
    reset_failed_subtasks(task)

    # Re-run validation
    return await handle_ai_review(task, log_callback)
