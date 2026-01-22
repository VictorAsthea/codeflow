from fastapi import APIRouter, HTTPException
import subprocess
from backend.config import settings

router = APIRouter()


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
