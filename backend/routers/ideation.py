"""
Router for Ideation feature endpoints.
Provides AI-powered project analysis, suggestions, and brainstorming chat.
"""

import asyncio
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend.config import settings
from backend.models import (
    Suggestion, IdeationChatRequest, SuggestionToTaskRequest,
    TaskCreate, SuggestionCategory, IdeationChatMessage,
    IdeationAnalysis, SuggestionStatus, ChatRequest, ChatResponse
)
from backend.services.ideation_service import get_ideation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ideation", tags=["ideation"])


def get_service():
    """Get ideation service for the active project."""
    from backend.services.storage_manager import get_active_project_path
    project_path = get_active_project_path() or settings.project_path
    return get_ideation_service(project_path)


@router.get("/state")
async def get_ideation_state():
    """
    Get current ideation state (suggestions + chat history).
    """
    try:
        service = get_service()
        state = service.get_state()
        return {
            "suggestions": [s for s in state.suggestions if not s.dismissed],
            "suggestions_count": len([s for s in state.suggestions if not s.dismissed]),
            "chat_history": state.chat_history,
            "last_analysis_at": state.last_analysis_at
        }
    except Exception as e:
        logger.error(f"Failed to get ideation state: {e}")
        raise HTTPException(500, f"Failed to get ideation state: {str(e)}")


@router.get("/suggestions")
async def get_suggestions(include_dismissed: bool = False):
    """
    Get all suggestions.

    Args:
        include_dismissed: Include dismissed suggestions (default: False)
    """
    try:
        service = get_service()
        suggestions = service.get_suggestions(include_dismissed=include_dismissed)
        return {
            "suggestions": suggestions,
            "count": len(suggestions)
        }
    except Exception as e:
        logger.error(f"Failed to get suggestions: {e}")
        raise HTTPException(500, f"Failed to get suggestions: {str(e)}")


@router.post("/analyze")
async def analyze_project():
    """
    Analyze the project and generate improvement suggestions.
    This scans the codebase for issues, security vulnerabilities,
    performance problems, and other improvements.

    Returns:
        List of new suggestions generated from analysis
    """
    try:
        service = get_service()
        suggestions = await service.analyze_project()
        return {
            "message": "Analysis complete",
            "suggestions": suggestions,
            "count": len(suggestions)
        }
    except Exception as e:
        logger.error(f"Project analysis failed: {e}")
        raise HTTPException(500, f"Analysis failed: {str(e)}")


@router.post("/generate")
async def generate_suggestions():
    """
    Generate creative suggestions for project improvements.
    Uses AI to brainstorm new features, enhancements, and ideas.

    Returns:
        List of new suggestions
    """
    try:
        service = get_service()
        suggestions = await service.generate_suggestions()
        return {
            "message": "Suggestions generated",
            "suggestions": suggestions,
            "count": len(suggestions)
        }
    except Exception as e:
        logger.error(f"Suggestion generation failed: {e}")
        raise HTTPException(500, f"Generation failed: {str(e)}")


@router.post("/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(suggestion_id: str):
    """
    Dismiss a suggestion.
    The suggestion will be hidden from the main list but not deleted.
    """
    service = get_service()
    success = service.dismiss_suggestion(suggestion_id)

    if not success:
        raise HTTPException(404, "Suggestion not found")

    return {"message": "Suggestion dismissed", "suggestion_id": suggestion_id}


@router.delete("/suggestions")
async def clear_all_suggestions():
    """
    Clear all suggestions.
    """
    service = get_service()
    count = service.clear_suggestions()
    return {"message": "All suggestions cleared", "count": count}


@router.post("/suggestions/{suggestion_id}/to-task")
async def convert_suggestion_to_task(suggestion_id: str):
    """
    Convert a suggestion to a task.
    Creates a new task based on the suggestion details.
    """
    service = get_service()
    suggestion = service.get_suggestion_by_id(suggestion_id)

    if not suggestion:
        raise HTTPException(404, "Suggestion not found")

    if suggestion.task_id:
        raise HTTPException(400, f"Suggestion already converted to task: {suggestion.task_id}")

    # Import here to avoid circular imports
    from backend.routers.tasks import create_new_task

    # Build task description from suggestion
    description = suggestion.description
    if suggestion.file_path:
        description += f"\n\nRelated file: {suggestion.file_path}"
        if suggestion.line_number:
            description += f" (line {suggestion.line_number})"

    # Create the task
    task_data = TaskCreate(
        title=suggestion.title,
        description=description
    )

    try:
        task = await create_new_task(task_data)

        # Mark suggestion as converted
        service.mark_suggestion_as_task(suggestion_id, task.id)

        return {
            "message": "Task created from suggestion",
            "task": task,
            "suggestion_id": suggestion_id
        }
    except Exception as e:
        logger.error(f"Failed to create task from suggestion: {e}")
        raise HTTPException(500, f"Failed to create task: {str(e)}")


@router.post("/chat")
async def chat_with_ideation(request: IdeationChatRequest):
    """
    Send a message to the ideation chat.
    Non-streaming version for simple requests.
    """
    try:
        service = get_service()
        response = await service.chat(request.message)
        return {
            "response": response,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Ideation chat failed: {e}")
        raise HTTPException(500, f"Chat failed: {str(e)}")


@router.get("/chat/history")
async def get_chat_history():
    """
    Get chat history.
    """
    service = get_service()
    history = service.get_chat_history()
    return {"history": history, "count": len(history)}


@router.delete("/chat/history")
async def clear_chat_history():
    """
    Clear chat history.
    """
    service = get_service()
    service.clear_chat_history()
    return {"message": "Chat history cleared"}


# WebSocket for streaming chat
class IdeationChatManager:
    """Manager for ideation chat WebSocket connections."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Ideation chat connected, total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"Ideation chat disconnected, total: {len(self.active_connections)}")

    async def send_message(self, websocket: WebSocket, message: dict):
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.warning(f"Failed to send message: {e}")
            self.disconnect(websocket)


# Global chat manager
ideation_chat_manager = IdeationChatManager()
