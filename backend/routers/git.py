from fastapi import APIRouter, HTTPException
import subprocess
import logging
from backend.config import settings
from backend.services import git_service
from backend.websocket_manager import kanban_manager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/git/sync-status")
async def get_sync_status():
    """Get the sync status of local develop vs origin/develop"""
    result = await git_service.get_sync_status(settings.project_path)
    return result


@router.post("/git/sync")
async def sync_develop():
    """
    Sync local develop with origin/develop.
    Emits git:synced WebSocket event on success.
    """
    # Broadcast syncing started
    await kanban_manager.broadcast("git:syncing", {
        "message": "Syncing with origin/develop..."
    })

    result = await git_service.pull_develop(settings.project_path)

    if result["success"]:
        # Broadcast sync completed
        await kanban_manager.broadcast("git:synced", {
            "message": result["message"],
            "commits_pulled": result["commits_pulled"]
        })
        logger.info(f"Git sync completed: {result['message']}")
        return result
    else:
        # Broadcast sync error
        await kanban_manager.broadcast("git:sync_error", {
            "message": result.get("error", "Unknown error")
        })
        raise HTTPException(status_code=500, detail=result.get("error", "Sync failed"))


@router.post("/sync-main")
async def sync_main():
    """Sync main branch with develop"""
    try:
        # Get current branch
        current_branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=settings.project_path,
            capture_output=True,
            text=True,
            check=True
        )
        current_branch = current_branch_result.stdout.strip()

        # Checkout main
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=settings.project_path,
            capture_output=True,
            text=True,
            check=True
        )

        # Pull from develop
        pull_result = subprocess.run(
            ["git", "pull", "origin", "develop"],
            cwd=settings.project_path,
            capture_output=True,
            text=True,
            check=True
        )

        # Push to origin
        push_result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=settings.project_path,
            capture_output=True,
            text=True,
            check=True
        )

        # Go back to original branch if it wasn't main
        if current_branch != "main":
            subprocess.run(
                ["git", "checkout", current_branch],
                cwd=settings.project_path,
                capture_output=True,
                text=True,
                check=True
            )

        return {
            "success": True,
            "message": "Main synced with develop successfully",
            "pull_output": pull_result.stdout,
            "push_output": push_result.stdout
        }

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        raise HTTPException(status_code=500, detail=f"Git sync failed: {error_msg}")
