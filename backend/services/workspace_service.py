"""
Service de gestion des workspaces multi-projets.
Stocke dans ~/.codeflow/workspaces.json
"""

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any


class WorkspaceService:
    """Gère les projets ouverts et la persistance."""

    def __init__(self):
        self.config_dir = self._get_config_dir()
        self.config_file = self.config_dir / "workspaces.json"
        self._ensure_config_dir()
        self.data = self._load()

    def _get_config_dir(self) -> Path:
        """Retourne le dossier de config global."""
        if os.name == 'nt':  # Windows
            base = os.environ.get('USERPROFILE', '')
        else:  # macOS/Linux
            base = os.environ.get('HOME', '')
        return Path(base) / ".codeflow"

    def _ensure_config_dir(self):
        """Crée le dossier de config si nécessaire."""
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> Dict[str, Any]:
        """Charge la configuration."""
        if self.config_file.exists():
            try:
                return json.loads(self.config_file.read_text())
            except:
                pass
        return {
            "version": "1.0",
            "open_projects": [],
            "active_project": None,
            "recent_projects": []
        }

    def _save(self):
        """Sauvegarde la configuration."""
        self.config_file.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))

    def get_workspace_state(self) -> Dict[str, Any]:
        """Retourne l'état complet du workspace."""
        # Reload from file to ensure fresh data
        self.data = self._load()

        projects = []
        for p in self.data["open_projects"]:
            project_info = dict(p)
            project_info["initialized"] = (Path(p["path"]) / ".codeflow" / "config.json").exists()
            project_info["exists"] = Path(p["path"]).exists()
            projects.append(project_info)

        return {
            "open_projects": projects,
            "active_project": self.data["active_project"],
            "recent_projects": self.data.get("recent_projects", [])
        }

    def _is_valid_project(self, path: Path) -> bool:
        """Vérifie si le dossier est un projet valide."""
        project_indicators = [
            "package.json",
            "requirements.txt",
            "pyproject.toml",
            "Cargo.toml",
            "go.mod",
            ".git",
            ".codeflow",
            "pom.xml",
            "build.gradle",
            "Makefile",
        ]
        return any((path / indicator).exists() for indicator in project_indicators)

    def open_project(self, project_path: str) -> Dict[str, Any]:
        """Ouvre un projet (ajoute aux onglets)."""
        path = str(Path(project_path).resolve())
        path_obj = Path(path)
        name = path_obj.name

        # Vérifier que c'est un vrai projet
        if not self._is_valid_project(path_obj):
            return {
                "success": False,
                "error": f"'{name}' n'est pas un projet valide (pas de package.json, .git, etc.)"
            }

        # Vérifier si déjà ouvert
        for p in self.data["open_projects"]:
            if p["path"] == path:
                self.data["active_project"] = path
                p["last_opened"] = datetime.now().isoformat()
                self._save()
                return {"success": True, "action": "activated", "project": p}

        # Ajouter le projet
        project = {
            "path": path,
            "name": name,
            "last_opened": datetime.now().isoformat()
        }
        self.data["open_projects"].append(project)
        self.data["active_project"] = path

        # Retirer des récents si présent
        if path in self.data.get("recent_projects", []):
            self.data["recent_projects"].remove(path)

        self._save()

        is_initialized = (Path(path) / ".codeflow" / "config.json").exists()

        return {
            "success": True,
            "action": "opened",
            "project": project,
            "initialized": is_initialized
        }

    def close_project(self, project_path: str) -> Dict[str, Any]:
        """Ferme un projet (retire des onglets)."""
        path = str(Path(project_path).resolve())

        if len(self.data["open_projects"]) <= 1:
            return {"success": False, "error": "Cannot close the last project"}

        self.data["open_projects"] = [
            p for p in self.data["open_projects"] if p["path"] != path
        ]

        # Ajouter aux récents
        if "recent_projects" not in self.data:
            self.data["recent_projects"] = []
        if path not in self.data["recent_projects"]:
            self.data["recent_projects"].insert(0, path)
            self.data["recent_projects"] = self.data["recent_projects"][:10]

        if self.data["active_project"] == path:
            self.data["active_project"] = self.data["open_projects"][0]["path"] if self.data["open_projects"] else None

        self._save()
        return {"success": True, "active_project": self.data["active_project"]}

    def set_active_project(self, project_path: str) -> Dict[str, Any]:
        """Définit le projet actif."""
        path = str(Path(project_path).resolve())

        for p in self.data["open_projects"]:
            if p["path"] == path:
                p["last_opened"] = datetime.now().isoformat()
                self.data["active_project"] = path
                self._save()
                return {"success": True, "active_project": path}

        return {"success": False, "error": "Project not open"}

    def get_recent_projects(self) -> List[str]:
        """Retourne les projets récents."""
        return self.data.get("recent_projects", [])

    def ensure_default_project(self, default_path: str):
        """S'assure qu'il y a au moins un projet ouvert."""
        if not self.data["open_projects"]:
            self.open_project(default_path)


# Singleton
_workspace_service = None

def get_workspace_service() -> WorkspaceService:
    global _workspace_service
    if _workspace_service is None:
        _workspace_service = WorkspaceService()
    return _workspace_service
