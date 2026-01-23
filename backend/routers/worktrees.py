from fastapi import APIRouter, HTTPException
from backend.config import settings
from backend.services.worktree_service import (
    list_worktrees,
    remove_worktree,
    merge_worktree,
    get_worktree_by_task_id
)

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
