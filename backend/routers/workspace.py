"""
Router pour les endpoints de gestion du workspace.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from pathlib import Path

from backend.services.workspace_service import get_workspace_service

router = APIRouter(prefix="/workspace", tags=["workspace"])


class ProjectPathRequest(BaseModel):
    project_path: str = Field(..., min_length=1, max_length=500)


@router.get("/state")
async def get_workspace_state():
    """Retourne l'état du workspace."""
    try:
        service = get_workspace_service()
        return service.get_workspace_state()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/open")
async def open_project(request: ProjectPathRequest):
    """Ouvre un projet."""
    try:
        service = get_workspace_service()
        return service.open_project(request.project_path)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/close")
async def close_project(request: ProjectPathRequest):
    """Ferme un projet."""
    try:
        service = get_workspace_service()
        return service.close_project(request.project_path)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/set-active")
async def set_active_project(request: ProjectPathRequest):
    """Définit le projet actif."""
    try:
        service = get_workspace_service()
        return service.set_active_project(request.project_path)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/recent")
async def get_recent_projects():
    """Retourne les projets récents."""
    service = get_workspace_service()
    return {"recent_projects": service.get_recent_projects()}


@router.get("/browse")
async def browse_folders(
    path: Optional[str] = Query(
        default=None,
        max_length=500,
        pattern=r"^(?!.*\.\.).*$",  # Rejette les chemins contenant ..
        description="Directory path to browse"
    )
):
    """
    Liste les dossiers pour le file browser.
    Si path est None, retourne le dossier Documents/DEV ou Home.
    """
    import os

    # Define allowed base directories
    home = Path.home()
    allowed_bases = [
        home,
        home / "Documents" / "DEV",
        home / "Documents",
    ]

    if path is None:
        # Démarrer dans Documents/DEV si existe, sinon Home
        dev_folder = home / "Documents" / "DEV"
        if dev_folder.exists():
            current = dev_folder
        else:
            current = home
    else:
        # Validate and resolve the path to prevent directory traversal
        try:
            requested_path = Path(path).resolve()

            # Check if the resolved path is within any allowed base directory
            path_allowed = False
            for base in allowed_bases:
                try:
                    requested_path.relative_to(base.resolve())
                    path_allowed = True
                    break
                except ValueError:
                    continue

            if not path_allowed:
                raise HTTPException(400, "Access to this directory is not allowed")

            current = requested_path
        except (OSError, ValueError):
            raise HTTPException(400, "Invalid path")

    if not current.exists():
        return {"current": str(Path.home()), "folders": []}

    folders = []
    try:
        for item in sorted(current.iterdir()):
            # Skip hidden folders and common non-project folders
            if item.name.startswith('.'):
                continue
            if item.name in ['node_modules', '__pycache__', 'venv', '.git', 'dist', 'build']:
                continue
            if not item.is_dir():
                continue

            # Check if it's a project (has common project files)
            is_project = any([
                (item / "package.json").exists(),
                (item / "requirements.txt").exists(),
                (item / "pyproject.toml").exists(),
                (item / "Cargo.toml").exists(),
                (item / "go.mod").exists(),
                (item / ".git").exists(),
                (item / ".codeflow").exists(),
            ])

            folders.append({
                "name": item.name,
                "path": str(item),
                "is_project": is_project
            })
    except PermissionError:
        pass

    return {
        "current": str(current),
        "parent": str(current.parent) if current.parent != current else None,
        "folders": folders
    }
