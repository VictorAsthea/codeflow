from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.config import settings
from backend.services.worktree_service import (
    list_worktrees,
    remove_worktree,
    merge_worktree,
    get_worktree_by_task_id,
    cleanup_worktree_files
)


class CleanupRequest(BaseModel):
    """Request body for cleanup endpoint"""
    patterns: list[str] | None = None
    keep_patterns: list[str] | None = None

router = APIRouter()


@router.get("/worktrees")
async def get_worktrees():
    """List all worktrees with their stats"""
    worktrees = await list_worktrees(settings.project_path)
    return {"worktrees": worktrees}


@router.delete("/worktrees/{task_id}")
async def delete_worktree(task_id: str):
    """Remove a worktree by task ID"""
    worktree = await get_worktree_by_task_id(settings.project_path, task_id)
    if not worktree:
        raise HTTPException(status_code=404, detail=f"Worktree for task {task_id} not found")

    result = await remove_worktree(settings.project_path, worktree['path'])

    if not result['success']:
        raise HTTPException(status_code=500, detail=result.get('error', 'Failed to remove worktree'))

    return {"message": f"Worktree for task {task_id} removed successfully"}


@router.post("/worktrees/{task_id}/merge")
async def merge_worktree_endpoint(task_id: str, target: str = "develop"):
    """Merge a worktree's branch into target branch"""
    worktree = await get_worktree_by_task_id(settings.project_path, task_id)
    if not worktree:
        raise HTTPException(status_code=404, detail=f"Worktree for task {task_id} not found")

    result = await merge_worktree(settings.project_path, worktree['path'], target)

    if not result['success']:
        raise HTTPException(status_code=500, detail=result.get('error', 'Failed to merge worktree'))

    return {"message": result.get('message', 'Merge successful')}


@router.post("/worktrees/{task_id}/cleanup")
async def cleanup_worktree_endpoint(task_id: str, request: CleanupRequest | None = None):
    """
    Clean up test/debug files from a worktree.

    Removes files matching cleanup patterns (e.g., test_*.py, .pytest_cache/)
    while preserving files in keep patterns (e.g., tests/**).

    Args:
        task_id: The task ID to identify the worktree
        request: Optional request body with custom patterns
            - patterns: List of glob patterns for files to remove (overrides defaults)
            - keep_patterns: List of glob patterns for files to keep (overrides defaults)

    Returns:
        Cleanup result with lists of cleaned files, directories, skipped items, and errors
    """
    worktree = await get_worktree_by_task_id(settings.project_path, task_id)
    if not worktree:
        raise HTTPException(status_code=404, detail=f"Worktree for task {task_id} not found")

    # Check if cleanup is enabled (can be overridden by providing explicit patterns)
    if not settings.cleanup_enabled and (request is None or request.patterns is None):
        return {
            "success": True,
            "message": "Cleanup is disabled in settings",
            "cleaned_files": [],
            "cleaned_dirs": [],
            "skipped": [],
            "errors": []
        }

    # Use provided patterns or fall back to settings defaults
    patterns = request.patterns if request and request.patterns else settings.cleanup_patterns
    keep_patterns = request.keep_patterns if request and request.keep_patterns else settings.cleanup_keep_patterns

    result = await cleanup_worktree_files(
        worktree_path=worktree['path'],
        patterns=patterns,
        keep_patterns=keep_patterns
    )

    if not result['success'] and result['errors']:
        # Partial failure - some files cleaned but had errors
        # Return 200 with the result so caller can see what was cleaned
        pass

    total_cleaned = len(result['cleaned_files']) + len(result['cleaned_dirs'])
    result['message'] = f"Cleaned {total_cleaned} items ({len(result['cleaned_files'])} files, {len(result['cleaned_dirs'])} directories)"

    return result
