"""
Router pour les endpoints de gestion de projet.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.services.project_init_service import get_project_init_service

router = APIRouter()


class InitRequest(BaseModel):
    project_path: Optional[str] = None


@router.get("/project/status")
async def get_project_status():
    """Retourne le statut d'initialisation du projet actuel."""
    try:
        service = get_project_init_service()
        return service.get_status()
    except Exception as e:
        raise HTTPException(500, f"Failed to get project status: {str(e)}")


@router.post("/project/init")
async def initialize_project(request: InitRequest = None):
    """Initialise Codeflow pour le projet actuel."""
    try:
        project_path = request.project_path if request else None
        service = get_project_init_service(project_path)

        if service.is_initialized():
            return {
                "success": False,
                "message": "Project is already initialized",
                "status": service.get_status()
            }

        return service.initialize()

    except Exception as e:
        raise HTTPException(500, f"Failed to initialize project: {str(e)}")
