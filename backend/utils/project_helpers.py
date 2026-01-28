"""
Helper functions for getting active project path.
Used across routers to ensure they work with the correct project.
"""

from backend.config import settings
from backend.services.workspace_service import get_workspace_service


def get_active_project_path() -> str:
    """
    Get the active project path from workspace service.
    Falls back to settings.project_path if no active project.
    """
    try:
        ws = get_workspace_service()
        state = ws.get_workspace_state()
        active = state.get("active_project")
        if active:
            return active
    except Exception:
        pass
    return settings.project_path
