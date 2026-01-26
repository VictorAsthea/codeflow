"""
Ideation API endpoints.

Provides endpoints for project analysis, AI-powered suggestions, and brainstorming chat.
"""

from fastapi import APIRouter, HTTPException
from datetime import datetime
import uuid

from backend.models import (
    IdeationAnalysis,
    IdeationData,
    Suggestion,
    SuggestionStatus,
    ChatRequest,
    ChatResponse,
    ChatMessage,
    Task,
    TaskStatus,
    Phase,
    PhaseConfig,
)
from backend.services.ideation_service import (
    IdeationStorage,
    analyze_project,
    generate_suggestions,
    chat_ideation,
    get_ideation_storage,
)
from backend.services.workspace_service import get_workspace_service
from backend.config import settings

router = APIRouter()


def _get_active_project_path() -> str:
    """Get the active project path from workspace service."""
    try:
        ws = get_workspace_service()
        state = ws.get_workspace_state()
        return state.get("active_project") or settings.project_path
    except Exception:
        return settings.project_path


def get_storage() -> IdeationStorage:
    """Get storage for the active project."""
    return get_ideation_storage(_get_active_project_path())


# ============== Analysis Endpoints ==============

@router.post("/ideation/analyze")
async def analyze_project_endpoint():
    """
    Analyze the project structure, patterns, and stack.

    Scans files, detects patterns (tests, CI/CD, linting), and counts lines.
    Results are cached in .codeflow/ideation/analysis.json
    """
    project_path = _get_active_project_path()
    analysis = await analyze_project(project_path)

    return {
        "analysis": analysis.model_dump(mode="json"),
        "message": f"Analyzed {analysis.files_count} files, {analysis.lines_count} lines"
    }


@router.get("/ideation/analysis")
async def get_analysis():
    """Get the cached project analysis."""
    storage = get_storage()
    data = storage.get_data()

    if not data.analysis:
        raise HTTPException(
            status_code=404,
            detail="No analysis found. Run POST /api/ideation/analyze first."
        )

    return {"analysis": data.analysis.model_dump(mode="json")}


# ============== Suggestions Endpoints ==============

@router.post("/ideation/suggest")
async def generate_suggestions_endpoint():
    """
    Generate AI-powered improvement suggestions.

    Analyzes the project (if not already done) and generates suggestions in categories:
    - Security: validation, auth, injection prevention
    - Performance: caching, optimization, lazy loading
    - Quality: tests, docs, refactoring
    - Feature: missing functionality
    """
    storage = get_storage()
    data = storage.get_data()

    # Run analysis if not done
    if not data.analysis:
        project_path = _get_active_project_path()
        data.analysis = await analyze_project(project_path)

    # Generate suggestions
    new_suggestions = await generate_suggestions(
        data.analysis,
        _get_active_project_path()
    )

    return {
        "suggestions": [s.model_dump(mode="json") for s in new_suggestions],
        "count": len(new_suggestions),
        "message": f"Generated {len(new_suggestions)} suggestions"
    }


@router.get("/ideation/suggestions")
async def list_suggestions():
    """List all suggestions."""
    storage = get_storage()
    data = storage.get_data()

    return {
        "suggestions": [s.model_dump(mode="json") for s in data.suggestions],
        "count": len(data.suggestions)
    }


@router.get("/ideation/suggestions/{suggestion_id}")
async def get_suggestion(suggestion_id: str):
    """Get a specific suggestion by ID."""
    storage = get_storage()
    suggestion = storage.get_suggestion(suggestion_id)

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    return {"suggestion": suggestion.model_dump(mode="json")}


@router.post("/ideation/suggestions/{suggestion_id}/accept")
async def accept_suggestion(suggestion_id: str):
    """
    Accept a suggestion and convert it to a Kanban task.

    Creates a new task in the backlog based on the suggestion.
    """
    from backend.services.storage_manager import get_project_storage

    storage = get_storage()
    suggestion = storage.get_suggestion(suggestion_id)

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if suggestion.status == SuggestionStatus.ACCEPTED:
        # Already accepted, return existing task
        if suggestion.task_id:
            task_storage = get_project_storage()
            existing_task = task_storage.get_task(suggestion.task_id)
            if existing_task:
                return {
                    "message": "Suggestion already accepted",
                    "task_id": suggestion.task_id,
                    "task": existing_task.model_dump(mode="json")
                }

    # Create task from suggestion
    task_id = f"task-{uuid.uuid4().hex[:8]}"

    # Map category to emoji for task title
    category_emojis = {
        "security": "🔒",
        "performance": "⚡",
        "quality": "📝",
        "feature": "✨"
    }
    emoji = category_emojis.get(suggestion.category.value, "💡")

    description = f"""## {emoji} {suggestion.title}

{suggestion.description}

### Details
- **Category**: {suggestion.category.value}
- **Priority**: {suggestion.priority}
- **Source**: AI Ideation Suggestion

---
*Generated from ideation suggestion {suggestion.id}*
"""

    default_config = PhaseConfig()
    task = Task(
        id=task_id,
        title=f"{emoji} {suggestion.title}",
        description=description,
        status=TaskStatus.BACKLOG,
        phases={
            "planning": Phase(name="planning", config=default_config),
            "coding": Phase(name="coding", config=default_config),
            "validation": Phase(name="validation", config=default_config),
        },
        created_at=datetime.now(),
        updated_at=datetime.now()
    )

    # Save task
    task_storage = get_project_storage()
    task_storage.create_task(task)

    # Update suggestion status
    storage.update_suggestion(suggestion_id, {
        "status": SuggestionStatus.ACCEPTED,
        "task_id": task_id
    })

    return {
        "message": "Suggestion accepted and converted to task",
        "task_id": task_id,
        "task": task.model_dump(mode="json")
    }


@router.post("/ideation/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(suggestion_id: str):
    """Dismiss a suggestion (mark as ignored)."""
    storage = get_storage()
    suggestion = storage.get_suggestion(suggestion_id)

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    updated = storage.update_suggestion(suggestion_id, {
        "status": SuggestionStatus.DISMISSED
    })

    return {
        "message": "Suggestion dismissed",
        "suggestion": updated.model_dump(mode="json") if updated else None
    }


@router.delete("/ideation/suggestions/{suggestion_id}")
async def delete_suggestion(suggestion_id: str):
    """Delete a suggestion permanently."""
    storage = get_storage()
    data = storage.get_data()

    # Filter out the suggestion
    original_count = len(data.suggestions)
    data.suggestions = [s for s in data.suggestions if s.id != suggestion_id]

    if len(data.suggestions) == original_count:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    storage.save_suggestions(data.suggestions)

    return {"message": "Suggestion deleted"}


# ============== Chat Endpoint ==============

@router.post("/ideation/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Brainstorm chat with AI assistant.

    Have a conversation about ideas, improvements, and technical approaches.
    The AI has context about the project analysis.
    """
    project_path = _get_active_project_path()

    # Convert request context to ChatMessage objects
    context = [
        ChatMessage(
            role=msg.role,
            content=msg.content,
            timestamp=msg.timestamp
        )
        for msg in request.context
    ]

    response, suggestions = await chat_ideation(
        message=request.message,
        context=context,
        project_path=project_path
    )

    return ChatResponse(
        response=response,
        suggestions=suggestions
    ).model_dump(mode="json")


# ============== Utility Endpoints ==============

@router.get("/ideation")
async def get_ideation_data():
    """Get all ideation data (analysis + suggestions)."""
    storage = get_storage()
    data = storage.get_data()

    return {
        "analysis": data.analysis.model_dump(mode="json") if data.analysis else None,
        "suggestions": [s.model_dump(mode="json") for s in data.suggestions],
        "suggestions_count": len(data.suggestions),
        "pending_count": len([s for s in data.suggestions if s.status == SuggestionStatus.PENDING]),
        "accepted_count": len([s for s in data.suggestions if s.status == SuggestionStatus.ACCEPTED]),
        "dismissed_count": len([s for s in data.suggestions if s.status == SuggestionStatus.DISMISSED])
    }


@router.delete("/ideation")
async def clear_ideation_data():
    """Clear all ideation data (for testing/reset)."""
    storage = get_storage()

    # Remove files if they exist
    if storage.analysis_file.exists():
        storage.analysis_file.unlink()
    if storage.suggestions_file.exists():
        storage.suggestions_file.unlink()

    return {"message": "Ideation data cleared"}
