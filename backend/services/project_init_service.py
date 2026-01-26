"""
Service d'initialisation de projet Codeflow.
"""

import json
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

from backend.services.stack_detector import StackDetector
from backend.config import settings


# Commandes de base toujours autorisées
BASE_COMMANDS = [
    ".", "[", "[[", "ag", "awk", "basename", "bash", "bc", "cat", "cd",
    "chmod", "clear", "cmp", "column", "comm", "cp", "curl", "cut", "date",
    "df", "diff", "dig", "dirname", "du", "echo", "env", "eval", "exec",
    "exit", "expand", "export", "expr", "false", "fd", "file", "find",
    "fmt", "fold", "git", "grep", "gunzip", "gzip", "head", "help", "host",
    "id", "jobs", "join", "jq", "kill", "less", "ln", "ls", "lsof", "man",
    "mkdir", "mktemp", "more", "mv", "nl", "paste", "pgrep", "ping", "pkill",
    "popd", "printenv", "printf", "ps", "pushd", "pwd", "read", "readlink",
    "realpath", "reset", "return", "rev", "rg", "rm", "rmdir", "sed", "seq",
    "set", "sh", "shuf", "sleep", "sort", "source", "split", "stat", "tail",
    "tar", "tee", "test", "time", "timeout", "touch", "tr", "tree", "true",
    "type", "uname", "unexpand", "uniq", "unset", "unzip", "watch", "wc",
    "wget", "whereis", "which", "whoami", "xargs", "yes", "yq", "zip", "zsh"
]


def detect_github_repo(project_path: Path) -> Optional[str]:
    """
    Détecte le repo GitHub depuis git remote.
    Retourne le format 'owner/repo' ou None.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            return None

        url = result.stdout.strip()

        # Parse different URL formats:
        # https://github.com/owner/repo.git
        # git@github.com:owner/repo.git
        # https://github.com/owner/repo

        patterns = [
            r'github\.com[:/]([^/]+)/([^/\.]+?)(?:\.git)?$',
            r'github\.com[:/]([^/]+)/([^/]+)$',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                owner, repo = match.groups()
                return f"{owner}/{repo}"

        return None
    except Exception:
        return None


def detect_default_branch(project_path: Path) -> str:
    """Détecte la branche par défaut (main ou develop si existe)."""
    try:
        # Check if develop branch exists
        result = subprocess.run(
            ["git", "branch", "--list", "develop"],
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.stdout.strip():
            return "develop"

        # Check remote develop
        result = subprocess.run(
            ["git", "branch", "-r", "--list", "origin/develop"],
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.stdout.strip():
            return "develop"

        return "main"
    except Exception:
        return "main"


class ProjectInitService:
    """Service d'initialisation de projet Codeflow."""

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.codeflow_dir = self.project_path / ".codeflow"
        self.detector = StackDetector(project_path)

    def is_initialized(self) -> bool:
        """Vérifie si le projet est déjà initialisé."""
        return self.codeflow_dir.exists() and (self.codeflow_dir / "config.json").exists()

    def get_status(self) -> Dict[str, Any]:
        """Retourne le statut d'initialisation."""
        if not self.is_initialized():
            return {
                "initialized": False,
                "project_path": str(self.project_path),
                "project_name": self.project_path.name
            }

        config = self._load_config()
        return {
            "initialized": True,
            "project_path": str(self.project_path),
            "project_name": config.get("project_name", self.project_path.name),
            "initialized_at": config.get("initialized_at"),
            "version": config.get("version")
        }

    def initialize(self) -> Dict[str, Any]:
        """Initialise le projet Codeflow."""

        # 1. Créer le dossier .codeflow
        self._create_directory_structure()

        # 2. Détecter le stack
        stack_info = self.detector.detect_all()

        # 3. Générer security.json
        self._generate_security_json(stack_info)

        # 4. Générer config.json
        self._generate_config_json(stack_info)

        # 5. Générer mcp.json
        self._generate_mcp_json(stack_info)

        # 6. Créer CLAUDE.md si absent
        created_claude_md = self._create_claude_md(stack_info)

        # 7. Mettre à jour .gitignore
        self._update_gitignore()

        files_created = [
            ".codeflow/config.json",
            ".codeflow/security.json",
            ".codeflow/mcp.json",
        ]
        if created_claude_md:
            files_created.append("CLAUDE.md")

        return {
            "success": True,
            "project_path": str(self.project_path),
            "project_name": self.project_path.name,
            "detected_stack": stack_info["detected_stack"],
            "files_created": files_created
        }

    def _create_directory_structure(self):
        """Crée la structure de dossiers."""
        directories = [
            self.codeflow_dir,
            self.codeflow_dir / "tasks",
            self.codeflow_dir / "specs",
            self.codeflow_dir / "logs",
            self.codeflow_dir / "sessions"
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def _generate_security_json(self, stack_info: Dict[str, Any]):
        """Génère le fichier security.json."""
        security = {
            "base_commands": BASE_COMMANDS,
            "stack_commands": stack_info["stack_commands"],
            "custom_commands": [],
            "detected_stack": stack_info["detected_stack"],
            "custom_scripts": stack_info["custom_scripts"],
            "project_dir": str(self.project_path),
            "created_at": stack_info["created_at"],
            "project_hash": stack_info["project_hash"]
        }

        security_file = self.codeflow_dir / "security.json"
        security_file.write_text(json.dumps(security, indent=2, ensure_ascii=False))

    def _generate_config_json(self, stack_info: Dict[str, Any]):
        """Génère le fichier config.json."""
        # Auto-detect GitHub repo and default branch
        github_repo = detect_github_repo(self.project_path)
        default_branch = detect_default_branch(self.project_path)

        config = {
            "version": "0.4",
            "project_name": self.project_path.name,
            "project_path": str(self.project_path),
            "initialized_at": datetime.now().isoformat(),
            "settings": {
                "auto_commit": True,
                "auto_push": True,
                "default_branch": default_branch,
                "worktrees_dir": ".worktrees",
                "language": "fr"
            },
            "github": {
                "repo": github_repo,
                "default_branch": default_branch
            },
            "phases": {
                "planning": {"enabled": True},
                "coding": {"enabled": True},
                "validation": {"enabled": True}
            },
            "detected_stack": stack_info["detected_stack"]
        }

        config_file = self.codeflow_dir / "config.json"
        config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False))

    def _generate_mcp_json(self, stack_info: Dict[str, Any]):
        """Génère le fichier mcp.json avec les MCPs recommandés."""
        detected = stack_info["detected_stack"]

        # Activer Puppeteer si projet web
        enable_puppeteer = (
            "javascript" in detected.get("languages", []) or
            "typescript" in detected.get("languages", [])
        )

        mcp = {
            "servers": {
                "context7": {
                    "enabled": True,
                    "command": "npx",
                    "args": ["-y", "@upstash/context7-mcp"],
                    "description": "Documentation des librairies"
                },
                "github": {
                    "enabled": True,
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "description": "PR, Issues, Webhooks"
                },
                "puppeteer": {
                    "enabled": enable_puppeteer,
                    "command": "npx",
                    "args": ["-y", "puppeteer-mcp-claude", "serve"],
                    "description": "Tests E2E navigateur"
                },
                "memory": {
                    "enabled": True,
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-memory"],
                    "description": "Memoire persistante"
                }
            },
            "auto_detected": True,
            "last_updated": datetime.now().isoformat()
        }

        mcp_file = self.codeflow_dir / "mcp.json"
        mcp_file.write_text(json.dumps(mcp, indent=2, ensure_ascii=False))

    def _create_claude_md(self, stack_info: Dict[str, Any]) -> bool:
        """Crée CLAUDE.md si absent. Retourne True si créé."""
        claude_md = self.project_path / "CLAUDE.md"

        if claude_md.exists():
            return False

        detected = stack_info["detected_stack"]
        all_stack = detected["languages"] + detected["frameworks"]
        stack_tags = ", ".join(all_stack) if all_stack else "Non detecte"

        # Commandes utiles
        commands = []
        scripts = stack_info["custom_scripts"]
        pm = detected["package_managers"][0] if detected["package_managers"] else "npm"

        if scripts.get("npm_scripts"):
            for script in scripts["npm_scripts"][:5]:
                commands.append(f"- `{pm} run {script}`")

        commands_str = "\n".join(commands) if commands else "- Aucune commande detectee"

        content = f'''# Instructions pour Claude Code

## Projet
- **Nom** : {self.project_path.name}
- **Stack** : {stack_tags}
- **Chemin** : {self.project_path}

## Conventions
- Langue des commits : Francais
- Format des branches : `task/{{id}}-{{slug}}`
- Tests requis avant merge : Oui

## Commandes utiles
{commands_str}

## Workflow Codeflow
1. Les taches sont gerees via Codeflow (Kanban)
2. Chaque tache cree un worktree isole
3. Phases : Planning -> Coding -> Validation
4. Auto-commit et push apres la phase Coding
5. Review humaine requise avant merge
'''

        claude_md.write_text(content, encoding='utf-8')
        return True

    def _update_gitignore(self):
        """Ajoute les entrées Codeflow au .gitignore."""
        gitignore = self.project_path / ".gitignore"

        entries = "\n# Codeflow\n.codeflow/logs/\n.codeflow/sessions/\n.worktrees/\n"

        existing = ""
        if gitignore.exists():
            existing = gitignore.read_text()

        if "# Codeflow" not in existing:
            gitignore.write_text(existing.rstrip() + entries)

    def _load_config(self) -> Dict[str, Any]:
        """Charge la configuration existante."""
        config_file = self.codeflow_dir / "config.json"
        if config_file.exists():
            return json.loads(config_file.read_text())
        return {}


def get_project_init_service(project_path: str = None) -> ProjectInitService:
    """Retourne une instance du service d'init."""
    if project_path is None:
        project_path = settings.project_path
    return ProjectInitService(project_path)
