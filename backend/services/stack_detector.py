"""
Service de détection automatique du stack technique.
Inspiré de Auto-Claude.
"""

import os
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime


class StackDetector:
    """Détecte automatiquement le stack technique d'un projet."""

    # Fichiers indicateurs par langage
    LANGUAGE_INDICATORS = {
        "python": ["requirements.txt", "setup.py", "pyproject.toml", "Pipfile"],
        "javascript": ["package.json"],
        "typescript": ["tsconfig.json"],
        "php": ["composer.json"],
        "ruby": ["Gemfile"],
        "go": ["go.mod", "go.sum"],
        "rust": ["Cargo.toml"],
        "java": ["pom.xml", "build.gradle"],
        "c": ["Makefile", "CMakeLists.txt"]
    }

    # Frameworks par fichier
    FRAMEWORK_INDICATORS = {
        "nextjs": ["next.config.js", "next.config.mjs", "next.config.ts"],
        "react": ["package.json:react"],
        "vue": ["vue.config.js", "package.json:vue"],
        "angular": ["angular.json"],
        "fastapi": ["requirements.txt:fastapi", "pyproject.toml:fastapi"],
        "django": ["manage.py"],
        "flask": ["requirements.txt:flask"],
        "express": ["package.json:express"],
        "tailwind": ["tailwind.config.js", "tailwind.config.ts"],
        "eslint": [".eslintrc", ".eslintrc.js", ".eslintrc.json"]
    }

    # Package managers
    PACKAGE_MANAGERS = {
        "npm": ["package-lock.json"],
        "yarn": ["yarn.lock"],
        "pnpm": ["pnpm-lock.yaml"],
        "bun": ["bun.lockb", "bun.lock"],
        "pip": ["requirements.txt"],
        "poetry": ["poetry.lock"],
        "composer": ["composer.lock"],
        "cargo": ["Cargo.lock"]
    }

    # Databases
    DATABASE_INDICATORS = {
        "postgresql": ["docker-compose.yml:postgres", ".env:POSTGRES"],
        "mysql": ["docker-compose.yml:mysql", ".env:MYSQL"],
        "mongodb": ["docker-compose.yml:mongo", ".env:MONGO"],
        "redis": ["docker-compose.yml:redis", ".env:REDIS"],
        "sqlite": [".env:SQLITE"]
    }

    # Cloud providers
    CLOUD_INDICATORS = {
        "supabase": [".env:SUPABASE", "supabase/"],
        "firebase": ["firebase.json"],
        "aws": [".env:AWS_"],
        "vercel": ["vercel.json"],
        "netlify": ["netlify.toml"]
    }

    # Commandes par stack
    STACK_COMMANDS = {
        "python": ["python", "python3", "pip", "pip3", "pipx"],
        "javascript": ["node", "npm", "npx"],
        "typescript": ["tsc", "ts-node", "tsx"],
        "bun": ["bun", "bunx"],
        "yarn": ["yarn"],
        "pnpm": ["pnpm"],
        "php": ["php", "composer"],
        "ruby": ["ruby", "gem", "bundle"],
        "go": ["go"],
        "rust": ["cargo", "rustc"],
        "nextjs": ["next"],
        "react": ["react-scripts"],
        "fastapi": ["uvicorn"],
        "django": ["django-admin"],
        "eslint": ["eslint"],
        "supabase": ["supabase"]
    }

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.detected = {
            "languages": [],
            "package_managers": [],
            "frameworks": [],
            "databases": [],
            "cloud_providers": []
        }
        self.custom_scripts = {
            "npm_scripts": [],
            "make_targets": [],
            "shell_scripts": []
        }

    def detect_all(self) -> Dict[str, Any]:
        """Détecte tout le stack du projet."""
        self._detect_languages()
        self._detect_package_managers()
        self._detect_frameworks()
        self._detect_databases()
        self._detect_cloud_providers()
        self._detect_custom_scripts()

        return {
            "detected_stack": self.detected,
            "custom_scripts": self.custom_scripts,
            "stack_commands": self._get_stack_commands(),
            "project_dir": str(self.project_path),
            "created_at": datetime.now().isoformat(),
            "project_hash": self._compute_project_hash()
        }

    def _file_exists(self, pattern: str) -> bool:
        """Vérifie si un fichier/pattern existe."""
        if pattern.endswith("/"):
            return (self.project_path / pattern).is_dir()
        return (self.project_path / pattern).exists()

    def _file_contains(self, filepath: str, search: str) -> bool:
        """Vérifie si un fichier contient une chaîne."""
        full_path = self.project_path / filepath
        if not full_path.exists():
            return False
        try:
            content = full_path.read_text(encoding='utf-8', errors='ignore')
            return search.lower() in content.lower()
        except:
            return False

    def _check_indicator(self, indicator: str) -> bool:
        """Vérifie un indicateur (fichier ou fichier:contenu)."""
        if ":" in indicator and not indicator.startswith(".env"):
            filepath, search = indicator.split(":", 1)
            return self._file_contains(filepath, search)
        return self._file_exists(indicator)

    def _detect_languages(self):
        """Détecte les langages utilisés."""
        for lang, indicators in self.LANGUAGE_INDICATORS.items():
            for indicator in indicators:
                if self._check_indicator(indicator):
                    if lang not in self.detected["languages"]:
                        self.detected["languages"].append(lang)
                    break

    def _detect_package_managers(self):
        """Détecte les package managers."""
        for pm, indicators in self.PACKAGE_MANAGERS.items():
            for indicator in indicators:
                if self._check_indicator(indicator):
                    if pm not in self.detected["package_managers"]:
                        self.detected["package_managers"].append(pm)
                    break

    def _detect_frameworks(self):
        """Détecte les frameworks."""
        for fw, indicators in self.FRAMEWORK_INDICATORS.items():
            for indicator in indicators:
                if self._check_indicator(indicator):
                    if fw not in self.detected["frameworks"]:
                        self.detected["frameworks"].append(fw)
                    break

    def _detect_databases(self):
        """Détecte les bases de données."""
        for db, indicators in self.DATABASE_INDICATORS.items():
            for indicator in indicators:
                if self._check_indicator(indicator):
                    if db not in self.detected["databases"]:
                        self.detected["databases"].append(db)
                    break

    def _detect_cloud_providers(self):
        """Détecte les providers cloud."""
        for provider, indicators in self.CLOUD_INDICATORS.items():
            for indicator in indicators:
                if self._check_indicator(indicator):
                    if provider not in self.detected["cloud_providers"]:
                        self.detected["cloud_providers"].append(provider)
                    break

    def _detect_custom_scripts(self):
        """Détecte les scripts personnalisés."""
        # NPM scripts
        package_json = self.project_path / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                self.custom_scripts["npm_scripts"] = list(data.get("scripts", {}).keys())
            except:
                pass

        # Makefile targets
        makefile = self.project_path / "Makefile"
        if makefile.exists():
            try:
                content = makefile.read_text()
                import re
                targets = re.findall(r'^([a-zA-Z_-]+):', content, re.MULTILINE)
                self.custom_scripts["make_targets"] = targets
            except:
                pass

        # Shell scripts
        for script in self.project_path.glob("*.sh"):
            self.custom_scripts["shell_scripts"].append(script.name)

    def _get_stack_commands(self) -> List[str]:
        """Retourne les commandes à autoriser selon le stack."""
        commands = []

        all_detected = (
            self.detected["languages"] +
            self.detected["package_managers"] +
            self.detected["frameworks"] +
            self.detected["cloud_providers"]
        )

        for item in all_detected:
            if item in self.STACK_COMMANDS:
                commands.extend(self.STACK_COMMANDS[item])

        return list(set(commands))

    def _compute_project_hash(self) -> str:
        """Calcule un hash unique pour le projet."""
        files_to_hash = ["package.json", "requirements.txt", "pyproject.toml", "Cargo.toml"]
        content = str(self.project_path)

        for f in files_to_hash:
            filepath = self.project_path / f
            if filepath.exists():
                content += filepath.read_text(errors='ignore')

        return hashlib.md5(content.encode()).hexdigest()
