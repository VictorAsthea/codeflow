from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from backend.services.worktree_service import (
    list_worktrees,
    remove_worktree,
    merge_worktree,
    get_worktree_by_task_id,
    check_worktree_health,
    cleanup_stale_worktrees,
    get_worktree_disk_usage
)
from backend.utils.project_helpers import get_active_project_path


class CleanupRequest(BaseModel):
    """Request body for cleanup endpoint"""
    max_age_hours: Optional[int] = 72


class CleanupRequest(BaseModel):
    """Request body for cleanup endpoint"""
    patterns: list[str] | None = None
    keep_patterns: list[str] | None = None

router = APIRouter()


@router.get("/worktrees")
async def get_worktrees():
    """List all worktrees with their stats"""
    worktrees = await list_worktrees(get_active_project_path())
    return {"worktrees": worktrees}


@router.delete("/worktrees/{task_id}")
async def delete_worktree(task_id: str):
    """Remove a worktree by task ID"""
    project_path = get_active_project_path()
    worktree = await get_worktree_by_task_id(project_path, task_id)
    if not worktree:
        raise HTTPException(status_code=404, detail=f"Worktree for task {task_id} not found")

    result = await remove_worktree(project_path, worktree['path'])

    if not result['success']:
        raise HTTPException(status_code=500, detail=result.get('error', 'Failed to remove worktree'))

    return {"message": f"Worktree for task {task_id} removed successfully"}


@router.post("/worktrees/{task_id}/merge")
async def merge_worktree_endpoint(
    task_id: str,
    target: str = Query(
        default="develop",
        max_length=100,
        pattern=r"^[a-zA-Z0-9_\-/.]+$",
        description="Target branch to merge into"
    )
):
    """Merge a worktree's branch into target branch"""
    project_path = get_active_project_path()
    worktree = await get_worktree_by_task_id(project_path, task_id)
    if not worktree:
        raise HTTPException(status_code=404, detail=f"Worktree for task {task_id} not found")

    result = await merge_worktree(project_path, worktree['path'], target)

    if not result['success']:
        raise HTTPException(status_code=500, detail=result.get('error', 'Failed to merge worktree'))

    return {"message": result.get('message', 'Merge successful')}


@router.get("/worktrees/health")
async def get_worktrees_health():
    """
    Get health status for all worktrees.

    Returns health information for each worktree including:
    - Whether the worktree is valid and accessible
    - Uncommitted changes status
    - Last activity timestamp
    - Any detected issues
    """
    project_path = get_active_project_path()
    worktrees = await list_worktrees(project_path)

    health_results = []
    for wt in worktrees:
        path = wt.get('path', '')
        health = await check_worktree_health(path)
        health_results.append({
            'path': path,
            'branch': wt.get('branch', ''),
            'task_id': wt.get('task_id'),
            'is_main': wt.get('is_main', False),
            **health
        })

    return {"worktrees": health_results}


@router.get("/worktrees/{task_id}/health")
async def get_worktree_health_by_task(task_id: str):
    """Get health status for a specific worktree by task ID"""
    project_path = get_active_project_path()
    worktree = await get_worktree_by_task_id(project_path, task_id)

    if not worktree:
        raise HTTPException(status_code=404, detail=f"Worktree for task {task_id} not found")

    health = await check_worktree_health(worktree['path'])

    return {
        'path': worktree['path'],
        'branch': worktree.get('branch', ''),
        'task_id': task_id,
        **health
    }


@router.post("/worktrees/cleanup")
async def cleanup_worktrees(request: CleanupRequest = CleanupRequest()):
    """
    Remove stale worktrees that have been inactive for a specified time.

    By default, removes worktrees inactive for more than 72 hours.
    Skips worktrees that:
    - Are the main worktree
    - Have uncommitted changes
    - Have recent activity
    """
    project_path = get_active_project_path()
    result = await cleanup_stale_worktrees(project_path, request.max_age_hours)

    return {
        "cleaned": result['cleaned'],
        "skipped": result['skipped'],
        "errors": result['errors'],
        "details": result['details']
    }


@router.get("/worktrees/disk-usage")
async def get_disk_usage():
    """
    Get disk usage for all worktrees.

    Returns total disk usage and per-worktree breakdown.
    Note: Main worktree is excluded from the calculation.
    """
    project_path = get_active_project_path()
    result = await get_worktree_disk_usage(project_path)

    return {
        "total_bytes": result['total_bytes'],
        "total_formatted": result['total_formatted'],
        "worktrees": result['worktrees']
    }
