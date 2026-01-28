"""
Discussion API endpoints.

Provides chat-based discussions for refining features and suggestions.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional

from backend.services.discussion_service import (
    DiscussionStorage,
    chat_discussion,
    get_discussion_storage,
)
from backend.services.roadmap_storage import RoadmapStorage
from backend.services.ideation_service import IdeationStorage
from backend.utils.project_helpers import get_active_project_path
from pathlib import Path

router = APIRouter()


class ChatRequest(BaseModel):
    """Request for sending a chat message."""
    message: str
    item_type: Literal["feature", "suggestion"]
    item_title: str
    item_description: str


class ChatResponse(BaseModel):
    """Response from chat."""
    response: str
    description_update: Optional[str] = None


def get_storage() -> DiscussionStorage:
    """Get storage for active project."""
    return get_discussion_storage(get_active_project_path())


@router.get("/discussions")
async def list_discussions():
    """List all discussions for the active project."""
    storage = get_storage()
    discussions = storage.list_discussions()
    return {"discussions": discussions, "count": len(discussions)}


@router.get("/discussions/{item_id}")
async def get_discussion(item_id: str):
    """Get a discussion by item ID."""
    storage = get_storage()
    discussion = storage.get_discussion(item_id)

    if not discussion:
        return {"discussion": None, "messages": []}

    return {
        "discussion": {
            "item_id": discussion.item_id,
            "item_type": discussion.item_type,
            "item_title": discussion.item_title,
            "created_at": discussion.created_at.isoformat() if discussion.created_at else None,
            "updated_at": discussion.updated_at.isoformat() if discussion.updated_at else None,
        },
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp.isoformat() if m.timestamp else None
            }
            for m in discussion.messages
        ]
    }


@router.post("/discussions/{item_id}/chat")
async def chat(item_id: str, request: ChatRequest):
    """
    Send a message in a discussion.

    Returns AI response and optional description update suggestion.
    """
    project_path = get_active_project_path()

    response, description_update = await chat_discussion(
        item_id=item_id,
        item_type=request.item_type,
        item_title=request.item_title,
        item_description=request.item_description,
        message=request.message,
        project_path=project_path
    )

    return ChatResponse(
        response=response,
        description_update=description_update
    )


@router.post("/discussions/{item_id}/apply-update")
async def apply_description_update(item_id: str, request: dict):
    """
    Apply a description update from a discussion to the feature/suggestion.

    Request body:
    - item_type: "feature" or "suggestion"
    - new_description: The new description to apply
    """
    item_type = request.get("item_type")
    new_description = request.get("new_description")

    if not item_type or not new_description:
        raise HTTPException(status_code=400, detail="item_type and new_description required")

    project_path = get_active_project_path()

    if item_type == "feature":
        # Update feature in roadmap
        storage = RoadmapStorage(base_path=Path(project_path))
        feature = storage.update_feature(item_id, {"description": new_description})
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")
        return {"success": True, "message": "Feature description updated"}

    elif item_type == "suggestion":
        # Update suggestion in ideation
        storage = IdeationStorage(project_path)
        suggestion = storage.update_suggestion(item_id, {"description": new_description})
        if not suggestion:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        return {"success": True, "message": "Suggestion description updated"}

    else:
        raise HTTPException(status_code=400, detail="Invalid item_type")


@router.delete("/discussions/{item_id}")
async def delete_discussion(item_id: str):
    """Delete a discussion."""
    storage = get_storage()
    if storage.delete_discussion(item_id):
        return {"success": True, "message": "Discussion deleted"}
    raise HTTPException(status_code=404, detail="Discussion not found")
