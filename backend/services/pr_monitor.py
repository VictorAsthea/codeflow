import asyncio
import subprocess
import logging
import json
from datetime import datetime
from typing import Optional
from backend.models import TaskStatus
from backend.services.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


def get_storage():
    """Get storage instance (lazy import to avoid circular dependency)"""
    from backend.main import storage
    return storage


class PRMonitor:
    def __init__(self, project_path: str, check_interval: int = 300):
        self.project_path = project_path
        self.check_interval = check_interval
        self.worktree_manager = WorktreeManager(project_path)
        self.running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start monitoring PRs for merged status"""
        if self.running:
            logger.warning("PR monitor already running")
            return

        self.running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("PR monitor started")

    async def stop(self):
        """Stop monitoring PRs"""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PR monitor stopped")

    async def _monitor_loop(self):
        """Main monitoring loop"""
        while self.running:
            try:
                await self._check_all_prs()
            except Exception as e:
                logger.error(f"Error in PR monitor loop: {e}", exc_info=True)

            await asyncio.sleep(self.check_interval)

    async def _check_all_prs(self):
        """Check all tasks with PRs for merged status"""
        tasks = get_storage().load_tasks()

        for task in tasks:
            if task.pr_number and not task.pr_merged and task.status == TaskStatus.DONE:
                try:
                    is_merged = await self._check_pr_merged(task.pr_number)
                    if is_merged:
                        await self._handle_pr_merged(task.id)
                except Exception as e:
                    logger.error(f"Error checking PR {task.pr_number} for task {task.id}: {e}")

    async def _check_pr_merged(self, pr_number: int) -> bool:
        """Check if a PR is merged using gh CLI"""
        try:
            result = subprocess.run(
                ["gh", "pr", "view", str(pr_number), "--json", "state,mergedAt"],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                check=True
            )

            pr_data = json.loads(result.stdout)
            return pr_data.get("state") == "MERGED" and pr_data.get("mergedAt") is not None

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to check PR {pr_number} status: {e.stderr}")
            return False
        except FileNotFoundError:
            logger.error("GitHub CLI (gh) is not installed")
            return False
        except Exception as e:
            logger.error(f"Error parsing PR data: {e}")
            return False

    async def _handle_pr_merged(self, task_id: str):
        """Handle a merged PR: cleanup worktree and mark task as done"""
        task = get_storage().get_task(task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return

        logger.info(f"PR #{task.pr_number} merged for task {task_id}, cleaning up...")

        task.pr_merged = True
        task.pr_merged_at = datetime.now()

        if task.worktree_path:
            try:
                self.worktree_manager.remove(task.id)
                logger.info(f"Worktree removed for task {task_id}")
            except Exception as e:
                logger.error(f"Failed to remove worktree for task {task_id}: {e}")

        get_storage().update_task(task)
        logger.info(f"Task {task_id} marked as merged and cleaned up")

    async def check_pr_status_by_webhook(self, pr_number: int, merged: bool, merged_at: Optional[str] = None):
        """Handle PR status update from webhook"""
        if not merged:
            return

        tasks = get_storage().load_tasks()
        for task in tasks:
            if task.pr_number == pr_number and not task.pr_merged:
                logger.info(f"Webhook received: PR #{pr_number} merged for task {task.id}")
                await self._handle_pr_merged(task.id)
                break
