"""
Router for Claude Code memory/session history.
Provides endpoints to view and manage past Claude Code sessions.
"""

import asyncio
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from backend.config import settings
from backend.models import ClaudeSession, SessionDetail
from backend.services.memory_service import get_memory_service
from backend.services.claude_runner import find_claude_cli

router = APIRouter()


@router.get("/memory/sessions", response_model=list[ClaudeSession])
async def get_sessions(
    project_path: Optional[str] = Query(None, description="Project path to filter sessions"),
    include_worktrees: bool = Query(True, description="Include sessions from worktrees"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of sessions to return")
):
    """
    Get Claude Code sessions for the current project.

    Returns sessions sorted by modification date (newest first).
    If no project_path is provided, uses the current active project.
    """
    memory_service = get_memory_service()

    # Use provided path or fall back to settings
    path = project_path or settings.project_path

    sessions = memory_service.get_sessions(
        project_path=path,
        include_worktrees=include_worktrees,
        limit=limit
    )

    return sessions


@router.get("/memory/sessions/{session_id}", response_model=SessionDetail)
async def get_session_detail(
    session_id: str,
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Get detailed information about a specific session including messages.

    Returns the full conversation history for the session.
    """
    memory_service = get_memory_service()
    path = project_path or settings.project_path

    session = memory_service.get_session_detail(session_id, path)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return session


@router.delete("/memory/sessions/{session_id}")
async def delete_session(
    session_id: str,
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Delete a session from Claude Code history.

    This removes the session file and updates the sessions index.
    """
    memory_service = get_memory_service()
    path = project_path or settings.project_path

    success = memory_service.delete_session(session_id, path)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found or could not be deleted")

    return {"message": "Session deleted", "session_id": session_id}


@router.post("/memory/sessions/{session_id}/resume")
async def resume_session(
    session_id: str,
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Resume a Claude Code session.

    Launches 'claude --resume {session_id}' in a new terminal.
    This opens an interactive Claude session that the user can continue.
    """
    memory_service = get_memory_service()
    path = project_path or settings.project_path

    # Verify session exists
    session = memory_service.get_session_detail(session_id, path)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.is_resumable:
        raise HTTPException(status_code=400, detail="Session is not resumable")

    # Find claude CLI
    claude_cmd = find_claude_cli()

    # Get the working directory (use worktree path if available, otherwise project path)
    working_dir = session.worktree_path or path

    # Launch claude --resume in a new terminal window
    # On Windows, use 'start' to open a new cmd window
    # On Unix, we could use xterm or gnome-terminal
    import platform
    import subprocess

    try:
        if platform.system() == "Windows":
            # Start a new cmd window with claude --resume
            subprocess.Popen(
                f'start cmd /k "{claude_cmd}" --resume {session_id}',
                shell=True,
                cwd=working_dir
            )
        else:
            # On Linux/Mac, try to detect available terminal
            # Default to running in background if no terminal found
            terminals = [
                ["gnome-terminal", "--", claude_cmd, "--resume", session_id],
                ["xterm", "-e", claude_cmd, "--resume", session_id],
                ["konsole", "-e", claude_cmd, "--resume", session_id],
            ]

            launched = False
            for term_cmd in terminals:
                try:
                    subprocess.Popen(term_cmd, cwd=working_dir)
                    launched = True
                    break
                except FileNotFoundError:
                    continue

            if not launched:
                # Fallback: run in background (not ideal but works)
                subprocess.Popen(
                    [claude_cmd, "--resume", session_id],
                    cwd=working_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to launch Claude session: {str(e)}"
        )

    return {
        "message": "Session resumed",
        "session_id": session_id,
        "working_dir": working_dir
    }
