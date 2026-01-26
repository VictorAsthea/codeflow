from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
import subprocess
import logging
from backend.config import settings
from backend.services import git_service
from backend.services.workspace_service import get_workspace_service
from backend.websocket_manager import kanban_manager

router = APIRouter()
logger = logging.getLogger(__name__)


def get_active_project_path() -> str:
    """Get the active project path from workspace service."""
    ws = get_workspace_service()
    state = ws.get_workspace_state()
    return state.get("active_project") or settings.project_path


class BranchDeleteRequest(BaseModel):
    """Request for deleting branches."""
    branches: List[str] = Field(..., min_length=1, max_length=50)
    force: bool = False


@router.get("/git/sync-status")
async def get_sync_status():
    """Get the sync status of local develop vs origin/develop for active project"""
    project_path = get_active_project_path()
    result = await git_service.get_sync_status(project_path)
    return result


@router.post("/git/sync")
async def sync_develop():
    """
    Sync local develop with origin/develop for active project.
    Emits git:synced WebSocket event on success.
    """
    project_path = get_active_project_path()

    # Broadcast syncing started
    await kanban_manager.broadcast("git:syncing", {
        "message": "Syncing with origin/develop..."
    })

    result = await git_service.pull_develop(project_path)

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
    """Sync main branch with develop for active project"""
    project_path = get_active_project_path()

    try:
        # Get current branch
        current_branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True
        )
        current_branch = current_branch_result.stdout.strip()

        # Checkout main
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True
        )

        # Pull from develop
        pull_result = subprocess.run(
            ["git", "pull", "origin", "develop"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True
        )

        # Push to origin
        push_result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True
        )

        # Go back to original branch if it wasn't main
        if current_branch != "main":
            subprocess.run(
                ["git", "checkout", current_branch],
                cwd=project_path,
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


@router.get("/git/branches")
async def list_branches():
    """
    List all branches for active project with their merge status.
    Returns branches categorized as merged or unmerged.
    """
    project_path = get_active_project_path()

    try:
        # Fetch to ensure we have latest remote info
        subprocess.run(
            ["git", "fetch", "--prune"],
            cwd=project_path,
            capture_output=True,
            text=True
        )

        # Get current branch
        current_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True
        )
        current_branch = current_result.stdout.strip()

        # Get all local branches
        all_branches_result = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True
        )
        all_branches = [b.strip() for b in all_branches_result.stdout.strip().split('\n') if b.strip()]

        # Get merged branches (into main or develop)
        merged_result = subprocess.run(
            ["git", "branch", "--merged", "develop", "--format=%(refname:short)"],
            cwd=project_path,
            capture_output=True,
            text=True
        )
        merged_branches = set()
        if merged_result.returncode == 0:
            merged_branches = set(b.strip() for b in merged_result.stdout.strip().split('\n') if b.strip())

        # Build branch list with details
        branches = []
        protected = {"main", "master", "develop", "dev"}

        for branch in all_branches:
            is_merged = branch in merged_branches
            is_protected = branch in protected
            is_current = branch == current_branch

            # Get last commit date
            date_result = subprocess.run(
                ["git", "log", "-1", "--format=%cr", branch],
                cwd=project_path,
                capture_output=True,
                text=True
            )
            last_commit = date_result.stdout.strip() if date_result.returncode == 0 else "unknown"

            branches.append({
                "name": branch,
                "is_merged": is_merged,
                "is_protected": is_protected,
                "is_current": is_current,
                "can_delete": is_merged and not is_protected and not is_current,
                "last_commit": last_commit
            })

        # Sort: current first, then by merged status, then alphabetically
        branches.sort(key=lambda b: (not b["is_current"], not b["is_merged"], b["name"]))

        return {
            "current_branch": current_branch,
            "total": len(branches),
            "merged_count": len([b for b in branches if b["is_merged"] and b["can_delete"]]),
            "branches": branches
        }

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        raise HTTPException(status_code=500, detail=f"Failed to list branches: {error_msg}")


@router.delete("/git/branches")
async def delete_branches(request: BranchDeleteRequest):
    """
    Delete specified branches from active project.
    Only deletes branches that are merged and not protected.
    """
    project_path = get_active_project_path()
    protected = {"main", "master", "develop", "dev"}

    # Get current branch to prevent deletion
    current_result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=project_path,
        capture_output=True,
        text=True
    )
    current_branch = current_result.stdout.strip() if current_result.returncode == 0 else ""

    deleted = []
    failed = []

    for branch in request.branches:
        # Safety checks
        if branch in protected:
            failed.append({"branch": branch, "reason": "Protected branch"})
            continue
        if branch == current_branch:
            failed.append({"branch": branch, "reason": "Cannot delete current branch"})
            continue

        try:
            # Use -d for safe delete (merged only) or -D for force
            flag = "-D" if request.force else "-d"
            result = subprocess.run(
                ["git", "branch", flag, branch],
                cwd=project_path,
                capture_output=True,
                text=True,
                check=True
            )
            deleted.append(branch)

            # Also delete remote branch if exists
            subprocess.run(
                ["git", "push", "origin", "--delete", branch],
                cwd=project_path,
                capture_output=True,
                text=True
            )

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else str(e)
            failed.append({"branch": branch, "reason": error_msg})

    return {
        "success": len(failed) == 0,
        "deleted": deleted,
        "deleted_count": len(deleted),
        "failed": failed
    }


@router.post("/git/cleanup-merged")
async def cleanup_merged_branches():
    """
    Automatically delete all merged branches (except protected ones).
    Convenience endpoint that combines list + delete.
    """
    project_path = get_active_project_path()
    protected = {"main", "master", "develop", "dev"}

    try:
        # Get current branch
        current_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True
        )
        current_branch = current_result.stdout.strip()

        # Get merged branches
        merged_result = subprocess.run(
            ["git", "branch", "--merged", "develop", "--format=%(refname:short)"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True
        )

        merged_branches = [
            b.strip() for b in merged_result.stdout.strip().split('\n')
            if b.strip() and b.strip() not in protected and b.strip() != current_branch
        ]

        if not merged_branches:
            return {
                "success": True,
                "message": "No merged branches to delete",
                "deleted": [],
                "deleted_count": 0
            }

        # Delete them
        deleted = []
        failed = []

        for branch in merged_branches:
            try:
                subprocess.run(
                    ["git", "branch", "-d", branch],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    check=True
                )
                deleted.append(branch)

                # Try to delete remote too
                subprocess.run(
                    ["git", "push", "origin", "--delete", branch],
                    cwd=project_path,
                    capture_output=True,
                    text=True
                )
            except subprocess.CalledProcessError as e:
                failed.append({"branch": branch, "reason": e.stderr.strip() if e.stderr else str(e)})

        return {
            "success": True,
            "message": f"Deleted {len(deleted)} merged branch(es)",
            "deleted": deleted,
            "deleted_count": len(deleted),
            "failed": failed
        }

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {error_msg}")
