"""
Service pour lire la configuration projet depuis .codeflow/config.json et security.json
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from backend.services.workspace_service import get_workspace_service


class ProjectConfigService:
    """Service pour accéder à la configuration d'un projet initialisé."""

    def __init__(self, project_path: Optional[str] = None):
        if project_path is None:
            project_path = self._get_active_project_path()
        self.project_path = Path(project_path) if project_path else None
        self.codeflow_dir = self.project_path / ".codeflow" if self.project_path else None

    def _get_active_project_path(self) -> Optional[str]:
        """Récupère le chemin du projet actif."""
        try:
            ws = get_workspace_service()
            state = ws.get_workspace_state()
            return state.get("active_project")
        except Exception:
            return None

    def is_initialized(self) -> bool:
        """Vérifie si le projet est initialisé avec Codeflow."""
        if not self.codeflow_dir:
            return False
        return (self.codeflow_dir / "config.json").exists()

    def get_config(self) -> Dict[str, Any]:
        """Retourne la configuration du projet."""
        if not self.is_initialized():
            return {}

        config_file = self.codeflow_dir / "config.json"
        try:
            return json.loads(config_file.read_text(encoding='utf-8'))
        except Exception:
            return {}

    def get_settings(self) -> Dict[str, Any]:
        """Retourne les settings du projet."""
        config = self.get_config()

        # Support legacy format (from json_storage)
        if "global" in config and "settings" not in config:
            # Map legacy global config to settings
            global_conf = config["global"]
            return {
                "auto_commit": True,  # Default
                "auto_push": True,    # Default
                "default_branch": global_conf.get("target_branch", "develop"),
                "language": "fr"
            }

        return config.get("settings", {})

    def get_security(self) -> Dict[str, Any]:
        """Retourne la configuration de sécurité."""
        if not self.codeflow_dir:
            return {}

        security_file = self.codeflow_dir / "security.json"
        if not security_file.exists():
            return {}

        try:
            return json.loads(security_file.read_text(encoding='utf-8'))
        except Exception:
            return {}

    def get_allowed_commands(self) -> List[str]:
        """
        Retourne la liste complète des commandes autorisées.
        Combine: base_commands + stack_commands + custom_commands
        """
        security = self.get_security()

        commands = []
        commands.extend(security.get("base_commands", []))
        commands.extend(security.get("stack_commands", []))
        commands.extend(security.get("custom_commands", []))

        # Dédupliquer tout en préservant l'ordre
        seen = set()
        unique_commands = []
        for cmd in commands:
            if cmd not in seen:
                seen.add(cmd)
                unique_commands.append(cmd)

        return unique_commands

    def get_mcp_config(self) -> Dict[str, Any]:
        """Retourne la configuration MCP."""
        if not self.codeflow_dir:
            return {}

        mcp_file = self.codeflow_dir / "mcp.json"
        if not mcp_file.exists():
            return {}

        try:
            return json.loads(mcp_file.read_text(encoding='utf-8'))
        except Exception:
            return {}

    def get_enabled_mcps(self) -> List[Dict[str, Any]]:
        """
        Retourne la liste des MCPs activés avec leur configuration.
        Format: [{"name": "context7", "command": "npx", "args": [...]}]
        """
        mcp_config = self.get_mcp_config()
        servers = mcp_config.get("servers", {})

        enabled = []
        for name, config in servers.items():
            if config.get("enabled", False):
                enabled.append({
                    "name": name,
                    "command": config.get("command"),
                    "args": config.get("args", [])
                })

        return enabled


    def update_settings(self, settings: Dict[str, Any]) -> bool:
        """Met à jour les settings du projet."""
        if not self.is_initialized():
            return False

        config = self.get_config()
        config["settings"] = {**config.get("settings", {}), **settings}

        config_file = self.codeflow_dir / "config.json"
        try:
            config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')
            return True
        except Exception:
            return False

    def update_security(self, custom_commands: List[str]) -> bool:
        """Met à jour les commandes personnalisées autorisées."""
        if not self.codeflow_dir:
            return False

        security = self.get_security()
        security["custom_commands"] = custom_commands

        security_file = self.codeflow_dir / "security.json"
        try:
            security_file.write_text(json.dumps(security, indent=2, ensure_ascii=False), encoding='utf-8')
            return True
        except Exception:
            return False

    def update_mcp(self, server_name: str, enabled: bool) -> bool:
        """Active/désactive un serveur MCP."""
        mcp_config = self.get_mcp_config()
        if server_name not in mcp_config.get("servers", {}):
            return False

        mcp_config["servers"][server_name]["enabled"] = enabled

        mcp_file = self.codeflow_dir / "mcp.json"
        try:
            mcp_file.write_text(json.dumps(mcp_config, indent=2, ensure_ascii=False), encoding='utf-8')
            return True
        except Exception:
            return False

    def get_github_config(self) -> Dict[str, Any]:
        """Retourne la configuration GitHub du projet."""
        config = self.get_config()

        # Support legacy format or new format
        if "github" in config:
            return config["github"]

        # Fallback: try to detect from git
        from backend.services.project_init_service import detect_github_repo, detect_default_branch
        return {
            "repo": detect_github_repo(self.project_path) if self.project_path else None,
            "default_branch": detect_default_branch(self.project_path) if self.project_path else "main"
        }

    def update_github_config(self, github_settings: Dict[str, Any]) -> bool:
        """Met à jour la configuration GitHub."""
        if not self.is_initialized():
            return False

        config = self.get_config()
        config["github"] = {**config.get("github", {}), **github_settings}

        config_file = self.codeflow_dir / "config.json"
        try:
            config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')
            return True
        except Exception:
            return False

    def verify_github_connection(self) -> Dict[str, Any]:
        """Vérifie la connexion au repo GitHub."""
        import subprocess

        github = self.get_github_config()
        repo = github.get("repo")

        if not repo:
            return {"connected": False, "error": "No repository configured"}

        try:
            # Try to fetch from origin to verify connection
            result = subprocess.run(
                ["git", "ls-remote", "--exit-code", "origin"],
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                return {"connected": True, "repo": repo}
            else:
                return {"connected": False, "error": "Cannot connect to remote"}

        except subprocess.TimeoutExpired:
            return {"connected": False, "error": "Connection timeout"}
        except Exception as e:
            return {"connected": False, "error": str(e)}


def get_project_config(project_path: Optional[str] = None) -> ProjectConfigService:
    """Fonction utilitaire pour obtenir la config d'un projet."""
    return ProjectConfigService(project_path)
