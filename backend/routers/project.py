"""
Router pour les endpoints de gestion de projet.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from backend.services.project_init_service import get_project_init_service
from backend.services.workspace_service import get_workspace_service
from backend.services.project_config_service import get_project_config

router = APIRouter()


class InitRequest(BaseModel):
    project_path: Optional[str] = None


class UpdateSettingsRequest(BaseModel):
    settings: Dict[str, Any]


class UpdateSecurityRequest(BaseModel):
    custom_commands: List[str]


class UpdateMCPRequest(BaseModel):
    server_name: str
    enabled: bool


class UpdateGitHubRequest(BaseModel):
    repo: Optional[str] = None
    default_branch: Optional[str] = None


def _get_active_project_path() -> str:
    """Retourne le chemin du projet actif depuis le workspace."""
    ws = get_workspace_service()
    state = ws.get_workspace_state()
    return state.get("active_project")


@router.get("/project/status")
async def get_project_status():
    """Retourne le statut d'initialisation du projet actuel."""
    try:
        project_path = _get_active_project_path()
        service = get_project_init_service(project_path)
        return service.get_status()
    except Exception as e:
        raise HTTPException(500, f"Failed to get project status: {str(e)}")


@router.post("/project/init")
async def initialize_project(request: InitRequest = None):
    """Initialise Codeflow pour le projet actuel."""
    try:
        project_path = request.project_path if request and request.project_path else _get_active_project_path()
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


@router.get("/project/config")
async def get_project_config_endpoint():
    """Retourne la configuration complète du projet (.codeflow/config.json)."""
    try:
        project_path = _get_active_project_path()
        config = get_project_config(project_path)

        if not config.is_initialized():
            raise HTTPException(404, "Project not initialized")

        return {
            "config": config.get_config(),
            "settings": config.get_settings(),
            "security": config.get_security(),
            "mcp": config.get_mcp_config(),
            "allowed_commands_count": len(config.get_allowed_commands()),
            "enabled_mcps": config.get_enabled_mcps()
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to get project config: {str(e)}")


@router.put("/project/settings")
async def update_project_settings(request: UpdateSettingsRequest):
    """Met à jour les settings du projet."""
    try:
        project_path = _get_active_project_path()
        config = get_project_config(project_path)

        if not config.is_initialized():
            raise HTTPException(404, "Project not initialized")

        success = config.update_settings(request.settings)
        if not success:
            raise HTTPException(500, "Failed to update settings")

        return {"success": True, "settings": config.get_settings()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to update settings: {str(e)}")


@router.get("/project/security")
async def get_project_security():
    """Retourne la configuration de sécurité du projet."""
    try:
        project_path = _get_active_project_path()
        config = get_project_config(project_path)

        if not config.is_initialized():
            raise HTTPException(404, "Project not initialized")

        security = config.get_security()
        return {
            "security": security,
            "all_commands": config.get_allowed_commands(),
            "custom_commands": security.get("custom_commands", [])
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to get security config: {str(e)}")


@router.put("/project/security")
async def update_project_security(request: UpdateSecurityRequest):
    """Met à jour les commandes personnalisées autorisées."""
    try:
        project_path = _get_active_project_path()
        config = get_project_config(project_path)

        if not config.is_initialized():
            raise HTTPException(404, "Project not initialized")

        success = config.update_security(request.custom_commands)
        if not success:
            raise HTTPException(500, "Failed to update security")

        return {"success": True, "custom_commands": request.custom_commands}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to update security: {str(e)}")


@router.get("/project/mcp")
async def get_project_mcp():
    """Retourne la configuration MCP du projet."""
    try:
        project_path = _get_active_project_path()
        config = get_project_config(project_path)

        if not config.is_initialized():
            raise HTTPException(404, "Project not initialized")

        return {
            "mcp": config.get_mcp_config(),
            "enabled": config.get_enabled_mcps()
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to get MCP config: {str(e)}")


@router.put("/project/mcp")
async def update_project_mcp(request: UpdateMCPRequest):
    """Active/désactive un serveur MCP."""
    try:
        project_path = _get_active_project_path()
        config = get_project_config(project_path)

        if not config.is_initialized():
            raise HTTPException(404, "Project not initialized")

        success = config.update_mcp(request.server_name, request.enabled)
        if not success:
            raise HTTPException(400, f"MCP server '{request.server_name}' not found")

        return {"success": True, "server": request.server_name, "enabled": request.enabled}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to update MCP: {str(e)}")


@router.get("/project/github")
async def get_project_github():
    """Retourne la configuration GitHub du projet."""
    try:
        project_path = _get_active_project_path()
        config = get_project_config(project_path)

        github = config.get_github_config()
        connection = config.verify_github_connection()

        return {
            "github": github,
            "connection": connection
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to get GitHub config: {str(e)}")


@router.put("/project/github")
async def update_project_github(request: UpdateGitHubRequest):
    """Met à jour la configuration GitHub du projet."""
    try:
        project_path = _get_active_project_path()
        config = get_project_config(project_path)

        # Build update dict with only provided fields
        updates = {}
        if request.repo is not None:
            updates["repo"] = request.repo
        if request.default_branch is not None:
            updates["default_branch"] = request.default_branch

        if not updates:
            raise HTTPException(400, "No fields to update")

        success = config.update_github_config(updates)
        if not success:
            raise HTTPException(500, "Failed to update GitHub config")

        return {"success": True, "github": config.get_github_config()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to update GitHub: {str(e)}")


@router.get("/project/github/verify")
async def verify_github_connection():
    """Vérifie la connexion au repo GitHub."""
    try:
        project_path = _get_active_project_path()
        config = get_project_config(project_path)
        return config.verify_github_connection()
    except Exception as e:
        raise HTTPException(500, f"Failed to verify GitHub connection: {str(e)}")
