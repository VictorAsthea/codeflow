"""
Service to cache project context and avoid rescanning for each task.
Context is stored in .codeflow/project_context.json
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta


class ProjectContext:
    """Caches project context to avoid rescanning."""

    CACHE_DURATION_HOURS = 24

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.codeflow_dir = self.project_path / ".codeflow"
        self.cache_file = self.codeflow_dir / "project_context.json"

    def get_context(self, force_refresh: bool = False) -> dict:
        """
        Returns project context.
        Uses cache if valid, otherwise scans the project.
        """
        if not force_refresh and self._is_cache_valid():
            return self._load_cache()

        context = self._scan_project()
        self._save_cache(context)
        return context

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid."""
        if not self.cache_file.exists():
            return False

        try:
            cache = self._load_cache()
            cache_time = datetime.fromisoformat(cache.get("scanned_at", "2000-01-01"))

            # Invalid if too old
            if datetime.now() - cache_time > timedelta(hours=self.CACHE_DURATION_HOURS):
                return False

            # Invalid if key files changed
            current_hash = self._hash_key_files()
            if cache.get("files_hash") != current_hash:
                return False

            return True
        except Exception:
            return False

    def _scan_project(self) -> dict:
        """Scan project and return context."""
        context = {
            "scanned_at": datetime.now().isoformat(),
            "project_path": str(self.project_path),
            "project_name": self.project_path.name,
            "stack": [],
            "frameworks": [],
            "structure": {},
            "key_files": [],
            "key_directories": [],
            "conventions": {},
            "files_hash": ""
        }

        # Detect stack from package.json
        package_json = self.project_path / "package.json"
        if package_json.exists():
            try:
                pkg = json.loads(package_json.read_text(encoding='utf-8'))
                context["stack"].append("node")

                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

                if "react" in deps:
                    context["frameworks"].append("react")
                if "next" in deps:
                    context["frameworks"].append("nextjs")
                if "vue" in deps:
                    context["frameworks"].append("vue")
                if "express" in deps:
                    context["frameworks"].append("express")
                if "fastify" in deps:
                    context["frameworks"].append("fastify")
                if "typescript" in deps:
                    context["stack"].append("typescript")
                if "tailwindcss" in deps:
                    context["conventions"]["styling"] = "tailwind"

            except Exception:
                pass

        # Detect Python stack
        requirements = self.project_path / "requirements.txt"
        pyproject = self.project_path / "pyproject.toml"

        if requirements.exists() or pyproject.exists():
            context["stack"].append("python")

            req_content = ""
            if requirements.exists():
                try:
                    req_content = requirements.read_text(encoding='utf-8').lower()
                except Exception:
                    pass
            if pyproject.exists():
                try:
                    req_content += pyproject.read_text(encoding='utf-8').lower()
                except Exception:
                    pass

            if "fastapi" in req_content:
                context["frameworks"].append("fastapi")
            if "django" in req_content:
                context["frameworks"].append("django")
            if "flask" in req_content:
                context["frameworks"].append("flask")

        # Detect key directories
        key_dirs = ["src", "lib", "app", "components", "pages", "api",
                    "backend", "frontend", "services", "utils", "models"]
        for dir_name in key_dirs:
            if (self.project_path / dir_name).is_dir():
                context["key_directories"].append(dir_name)

        # Detect key files
        key_file_patterns = [
            "README.md", "package.json", "requirements.txt", "pyproject.toml",
            "tsconfig.json", "vite.config.ts", "next.config.js", "tailwind.config.js",
            ".env.example", "docker-compose.yml", "Dockerfile"
        ]
        for pattern in key_file_patterns:
            if (self.project_path / pattern).exists():
                context["key_files"].append(pattern)

        # Scan structure (2 levels)
        context["structure"] = self._scan_structure(self.project_path, max_depth=2)

        # Conventions
        if (self.project_path / "tsconfig.json").exists():
            context["conventions"]["typescript"] = True
        if (self.project_path / ".eslintrc.js").exists() or (self.project_path / ".eslintrc.json").exists():
            context["conventions"]["eslint"] = True
        if (self.project_path / ".prettierrc").exists():
            context["conventions"]["prettier"] = True

        context["files_hash"] = self._hash_key_files()

        return context

    def _scan_structure(self, path: Path, max_depth: int, current_depth: int = 0) -> dict:
        """Scan project structure."""
        if current_depth >= max_depth:
            return {}

        structure = {}
        ignore_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv',
                       '.next', 'dist', 'build', '.codeflow', '.worktrees'}

        try:
            for item in sorted(path.iterdir()):
                if item.name.startswith('.') and item.name not in ['.env.example']:
                    continue
                if item.name in ignore_dirs:
                    continue

                if item.is_dir():
                    structure[item.name + "/"] = self._scan_structure(
                        item, max_depth, current_depth + 1
                    )
                else:
                    structure[item.name] = "file"
        except PermissionError:
            pass

        return structure

    def _hash_key_files(self) -> str:
        """Hash key files to detect changes."""
        content = ""
        for pattern in ["package.json", "requirements.txt", "pyproject.toml"]:
            path = self.project_path / pattern
            if path.exists():
                try:
                    content += path.read_text(encoding='utf-8')[:2000]
                except Exception:
                    pass
        return hashlib.md5(content.encode()).hexdigest()

    def _load_cache(self) -> dict:
        """Load cache from file."""
        return json.loads(self.cache_file.read_text(encoding='utf-8'))

    def _save_cache(self, context: dict):
        """Save cache to file."""
        self.codeflow_dir.mkdir(exist_ok=True)
        self.cache_file.write_text(json.dumps(context, indent=2), encoding='utf-8')

    def invalidate(self):
        """Force rescan on next call."""
        if self.cache_file.exists():
            self.cache_file.unlink()

    def get_context_for_prompt(self) -> str:
        """Returns context formatted for prompt inclusion."""
        ctx = self.get_context()

        lines = [
            f"Project: {ctx['project_name']}",
            f"Stack: {', '.join(ctx['stack'])}",
        ]

        if ctx['frameworks']:
            lines.append(f"Frameworks: {', '.join(ctx['frameworks'])}")

        if ctx['key_directories']:
            lines.append(f"Key directories: {', '.join(ctx['key_directories'])}")

        if ctx['conventions']:
            conv = [f"{k}={v}" for k, v in ctx['conventions'].items()]
            lines.append(f"Conventions: {', '.join(conv)}")

        return "\n".join(lines)


# Singleton to avoid recreating instance
_project_contexts: dict[str, ProjectContext] = {}


def get_project_context(project_path: str) -> ProjectContext:
    """Returns ProjectContext instance for a project."""
    if project_path not in _project_contexts:
        _project_contexts[project_path] = ProjectContext(project_path)
    return _project_contexts[project_path]
