"""
Router pour les endpoints de contexte projet.
"""

from fastapi import APIRouter, HTTPException

from backend.services.project_context import get_project_context
from backend.utils.project_helpers import get_active_project_path

router = APIRouter(prefix="/api/context", tags=["context"])


@router.get("")
async def get_context():
    """
    Retourne le contexte du projet actuel.
    """
    project_path = get_active_project_path()

    try:
        ctx = get_project_context(project_path)
        context_data = ctx.get_context()

        # Ajouter des infos supplémentaires
        context_data["is_cached"] = ctx._is_cache_valid()
        context_data["cache_file"] = str(ctx.cache_file)

        return context_data

    except Exception as e:
        raise HTTPException(500, f"Failed to get project context: {str(e)}")


@router.post("/refresh")
async def refresh_context():
    """
    Force un rafraîchissement du contexte (rescan du projet).
    """
    project_path = get_active_project_path()

    try:
        ctx = get_project_context(project_path)
        ctx.invalidate()  # Invalide le cache
        context_data = ctx.get_context(force_refresh=True)  # Force rescan

        return {
            "message": "Context refreshed successfully",
            "context": context_data
        }

    except Exception as e:
        raise HTTPException(500, f"Failed to refresh context: {str(e)}")


@router.get("/summary")
async def get_context_summary():
    """
    Retourne un résumé court du contexte (pour affichage dans header/sidebar).
    """
    project_path = get_active_project_path()

    try:
        ctx = get_project_context(project_path)
        context_data = ctx.get_context()

        return {
            "project_name": context_data.get("project_name", "Unknown"),
            "stack": context_data.get("stack", []),
            "frameworks": context_data.get("frameworks", []),
            "scanned_at": context_data.get("scanned_at")
        }

    except Exception as e:
        return {
            "project_name": "Unknown",
            "stack": [],
            "frameworks": [],
            "scanned_at": None,
            "error": str(e)
        }
