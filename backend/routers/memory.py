"""
Memory router for session history management.

Provides endpoints for:
- Listing all sessions or sessions by task
- Getting session details with conversation
- Saving sessions after Claude Code execution
- Deleting sessions
- Resuming sessions with --resume
"""

from fastapi import APIRouter, HTTPException
from typing import Optional

from backend.models import Session, SessionDetail, SessionCreate, ResumeInfo

router = APIRouter(prefix="/memory", tags=["memory"])


def get_memory_service():
    """Get memory service with active project path."""
    from backend.services.memory_service import get_memory_service as get_service
    from backend.services.workspace_service import get_workspace_service

    try:
        ws = get_workspace_service()
        state = ws.get_workspace_state()
        project_path = state.get("active_project")
        if project_path:
            from pathlib import Path
            return get_service(base_path=Path(project_path))
    except Exception:
        pass

    return get_service()


@router.get("/sessions", response_model=list[Session])
async def list_sessions(task_id: Optional[str] = None):
    """
    List all sessions, optionally filtered by task ID.

    Args:
        task_id: Optional task ID to filter sessions

    Returns:
        List of session metadata
    """
    try:
        service = get_memory_service()
        sessions = service.list_sessions(task_id=task_id)

        return [Session(**s) for s in sessions]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{task_id}", response_model=list[Session])
async def list_sessions_by_task(task_id: str):
    """
    List all sessions for a specific task.

    Args:
        task_id: The task ID to get sessions for

    Returns:
        List of session metadata for the task
    """
    try:
        service = get_memory_service()
        sessions = service.list_sessions(task_id=task_id)

        return [Session(**s) for s in sessions]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str):
    """
    Get session details including conversation history.

    Args:
        session_id: The session ID

    Returns:
        Session details with conversation
    """
    try:
        service = get_memory_service()
        session = service.get_session(session_id)

        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        return SessionDetail(**session)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{task_id}", response_model=Session)
async def save_session(task_id: str, data: SessionCreate):
    """
    Save a new session after Claude Code execution.

    Args:
        task_id: The task ID this session belongs to
        data: Session data including messages, tokens, etc.

    Returns:
        The saved session metadata
    """
    try:
        service = get_memory_service()

        session_data = {
            "task_title": data.task_title,
            "worktree": data.worktree,
            "started_at": data.started_at.isoformat() if data.started_at else None,
            "ended_at": data.ended_at.isoformat() if data.ended_at else None,
            "status": data.status.value,
            "messages_count": data.messages_count,
            "tokens_used": data.tokens_used,
            "claude_session_id": data.claude_session_id,
            "messages": data.messages,
            "raw_output": data.raw_output,
            "error": data.error
        }

        result = service.save_session(task_id, session_data)

        return Session(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """
    Delete a session and its conversation data.

    Args:
        session_id: The session ID to delete

    Returns:
        Success message
    """
    try:
        service = get_memory_service()
        deleted = service.delete_session(session_id)

        if not deleted:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        return {"message": f"Session {session_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/session/{session_id}/resume", response_model=ResumeInfo)
async def get_resume_info(session_id: str):
    """
    Get information needed to resume a session with --resume.

    Args:
        session_id: The session ID to resume

    Returns:
        Resume info including claude_session_id for --resume flag
    """
    try:
        service = get_memory_service()
        resume_info = service.get_resume_info(session_id)

        if not resume_info:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        return ResumeInfo(**resume_info)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import")
async def import_claude_sessions(project_path: Optional[str] = None):
    """
    Import sessions from ~/.claude/projects/ if available.

    This reads Claude's native session storage and imports relevant sessions.

    Args:
        project_path: Optional project path to filter sessions

    Returns:
        List of imported sessions
    """
    try:
        service = get_memory_service()
        imported = service.import_from_claude_projects(project_path)

        return {
            "message": f"Imported {len(imported)} sessions",
            "sessions": [Session(**s) for s in imported]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
