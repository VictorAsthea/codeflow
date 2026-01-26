"""
Ideation service for project analysis and AI-powered suggestions.

Provides functionality to:
- Analyze project structure, detect patterns, and count lines
- Generate improvement suggestions via Claude AI
- Conduct brainstorm chat sessions
"""

import json
import uuid
import logging
import asyncio
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# fcntl only available on Unix
if sys.platform != 'win32':
    import fcntl

from backend.models import (
    IdeationAnalysis,
    IdeationData,
    Suggestion,
    SuggestionCategory,
    SuggestionStatus,
    ChatMessage,
)
from backend.services.roadmap_ai import call_claude, extract_json_array, get_claude_command
from backend.config import settings

logger = logging.getLogger(__name__)


class IdeationStorage:
    """Storage for ideation data in .codeflow/ideation/"""

    def __init__(self, project_path: Optional[str] = None):
        self.project_path = Path(project_path or settings.project_path)
        self.ideation_dir = self.project_path / ".codeflow" / "ideation"
        self.analysis_file = self.ideation_dir / "analysis.json"
        self.suggestions_file = self.ideation_dir / "suggestions.json"
        self.ideas_dir = self.ideation_dir / "ideas"

    def _ensure_dirs(self):
        """Ensure storage directories exist."""
        self.ideation_dir.mkdir(parents=True, exist_ok=True)
        self.ideas_dir.mkdir(parents=True, exist_ok=True)

    def _atomic_write_suggestions(self, suggestions: list[Suggestion]):
        """Atomically write suggestions with file locking."""
        self._ensure_dirs()

        # Create lock file
        lock_file = self.suggestions_file.with_suffix('.lock')

        try:
            # Open lock file and acquire exclusive lock (Unix only)
            with open(lock_file, 'w') as lock_fd:
                if sys.platform != 'win32':
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)

                # Write to temporary file first
                temp_file = self.suggestions_file.with_suffix('.tmp')
                temp_file.write_text(
                    json.dumps([s.model_dump(mode="json") for s in suggestions], indent=2, default=str),
                    encoding="utf-8"
                )

                # Atomic move
                temp_file.replace(self.suggestions_file)

        finally:
            # Clean up lock file
            if lock_file.exists():
                lock_file.unlink()

    def get_data(self) -> IdeationData:
        """Load all ideation data."""
        analysis = None
        suggestions = []

        if self.analysis_file.exists():
            try:
                data = json.loads(self.analysis_file.read_text(encoding="utf-8"))
                analysis = IdeationAnalysis(**data)
            except Exception as e:
                logger.warning(f"Failed to load analysis: {e}")

        if self.suggestions_file.exists():
            try:
                data = json.loads(self.suggestions_file.read_text(encoding="utf-8"))
                suggestions = [Suggestion(**s) for s in data]
            except Exception as e:
                logger.warning(f"Failed to load suggestions: {e}")

        return IdeationData(analysis=analysis, suggestions=suggestions)

    def save_analysis(self, analysis: IdeationAnalysis):
        """Save analysis data."""
        self._ensure_dirs()
        self.analysis_file.write_text(
            json.dumps(analysis.model_dump(mode="json"), indent=2, default=str),
            encoding="utf-8"
        )

    def save_suggestions(self, suggestions: list[Suggestion]):
        """Save suggestions data."""
        self._atomic_write_suggestions(suggestions)

    def get_suggestion(self, suggestion_id: str) -> Optional[Suggestion]:
        """Get a specific suggestion by ID."""
        data = self.get_data()
        for s in data.suggestions:
            if s.id == suggestion_id:
                return s
        return None

    def update_suggestion(self, suggestion_id: str, updates: dict) -> Optional[Suggestion]:
        """Update a suggestion atomically."""
        data = self.get_data()
        for i, s in enumerate(data.suggestions):
            if s.id == suggestion_id:
                updated = s.model_copy(update=updates)
                data.suggestions[i] = updated
                self._atomic_write_suggestions(data.suggestions)
                return updated
        return None

    def delete_suggestion(self, suggestion_id: str) -> bool:
        """Delete a suggestion atomically."""
        data = self.get_data()
        original_count = len(data.suggestions)
        data.suggestions = [s for s in data.suggestions if s.id != suggestion_id]

        if len(data.suggestions) == original_count:
            return False  # Suggestion not found

        self._atomic_write_suggestions(data.suggestions)
        return True


def generate_suggestion_id() -> str:
    """Generate a unique suggestion ID."""
    return f"sug-{uuid.uuid4().hex[:8]}"


def _scan_project_sync(path: Path, analysis: IdeationAnalysis) -> IdeationAnalysis:
    """Synchronous project scanning helper for thread execution."""
    # Directories to ignore
    ignore_dirs = {
        '.git', 'node_modules', '__pycache__', '.venv', 'venv',
        '.next', 'dist', 'build', '.codeflow', '.worktrees',
        'coverage', '.nyc_output', '.pytest_cache', '.mypy_cache'
    }

    # Extensions to count
    code_extensions = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.vue', '.svelte',
        '.java', '.go', '.rs', '.rb', '.php', '.cs', '.cpp', '.c', '.h',
        '.html', '.css', '.scss', '.sass', '.less'
    }

    try:
        # Scan files and count lines
        for file_path in path.rglob("*"):
            if file_path.is_file():
                # Get relative path parts to check against ignore dirs
                try:
                    relative_parts = file_path.relative_to(path).parts
                except ValueError:
                    relative_parts = file_path.parts

                # Skip ignored directories
                if any(part in ignore_dirs for part in relative_parts):
                    continue

                # Count code files
                if file_path.suffix.lower() in code_extensions:
                    analysis.files_count += 1
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        analysis.lines_count += len(content.splitlines())
                    except Exception:
                        pass

        # Detect stack from package.json
        package_json = path / "package.json"
        if package_json.exists():
            try:
                pkg = json.loads(package_json.read_text(encoding="utf-8"))
                analysis.stack.append("node")
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

                if "react" in deps:
                    analysis.frameworks.append("react")
                if "next" in deps:
                    analysis.frameworks.append("nextjs")
                if "vue" in deps:
                    analysis.frameworks.append("vue")
                if "express" in deps:
                    analysis.frameworks.append("express")
                if "fastify" in deps:
                    analysis.frameworks.append("fastify")
                if "typescript" in deps:
                    analysis.stack.append("typescript")
            except Exception as e:
                logger.warning(f"Error reading package.json: {e}")

        # Detect Python stack
        requirements = path / "requirements.txt"
        pyproject = path / "pyproject.toml"

        if requirements.exists() or pyproject.exists():
            analysis.stack.append("python")

            req_content = ""
            if requirements.exists():
                try:
                    req_content = requirements.read_text(encoding="utf-8").lower()
                except Exception:
                    pass
            if pyproject.exists():
                try:
                    req_content += pyproject.read_text(encoding="utf-8").lower()
                except Exception:
                    pass

            if "fastapi" in req_content:
                analysis.frameworks.append("fastapi")
            if "django" in req_content:
                analysis.frameworks.append("django")
            if "flask" in req_content:
                analysis.frameworks.append("flask")

        # Detect Rust
        if (path / "Cargo.toml").exists():
            analysis.stack.append("rust")

        # Detect Go
        if (path / "go.mod").exists():
            analysis.stack.append("go")

        # Detect key directories
        key_dirs = [
            "src", "lib", "app", "components", "pages", "api",
            "backend", "frontend", "services", "utils", "models",
            "tests", "test", "__tests__", "spec"
        ]
        for dir_name in key_dirs:
            if (path / dir_name).is_dir():
                analysis.key_directories.append(dir_name)

        # Detect patterns
        patterns = []

        # Check for testing patterns
        if (path / "tests").is_dir() or (path / "test").is_dir() or (path / "__tests__").is_dir():
            patterns.append("unit_tests")
        if (path / "pytest.ini").exists() or (path / "conftest.py").exists():
            patterns.append("pytest")
        if (path / "jest.config.js").exists() or (path / "jest.config.ts").exists():
            patterns.append("jest")

        # Check for CI/CD
        if (path / ".github" / "workflows").is_dir():
            patterns.append("github_actions")
        if (path / ".gitlab-ci.yml").exists():
            patterns.append("gitlab_ci")
        if (path / "Dockerfile").exists():
            patterns.append("docker")
        if (path / "docker-compose.yml").exists() or (path / "docker-compose.yaml").exists():
            patterns.append("docker_compose")

        # Check for linting/formatting
        if (path / ".eslintrc.js").exists() or (path / ".eslintrc.json").exists():
            patterns.append("eslint")
        if (path / ".prettierrc").exists() or (path / ".prettierrc.json").exists():
            patterns.append("prettier")
        if (path / "pyproject.toml").exists():
            try:
                content = (path / "pyproject.toml").read_text(encoding="utf-8")
                if "ruff" in content:
                    patterns.append("ruff")
                if "black" in content:
                    patterns.append("black")
            except Exception:
                pass

        # Check for documentation
        if (path / "docs").is_dir():
            patterns.append("documentation")
        if (path / "README.md").exists():
            patterns.append("readme")

        analysis.patterns_detected = patterns

    except Exception as e:
        logger.error(f"Error analyzing project: {e}")

    return analysis


async def analyze_project(project_path: Optional[str] = None) -> IdeationAnalysis:
    """
    Analyze project structure, detect patterns, and count lines.

    Args:
        project_path: Path to project root

    Returns:
        IdeationAnalysis with detected information
    """
    path = Path(project_path or settings.project_path)

    analysis = IdeationAnalysis(
        project_path=str(path),
        project_name=path.name,
        stack=[],
        frameworks=[],
        files_count=0,
        lines_count=0,
        key_directories=[],
        patterns_detected=[],
        analyzed_at=datetime.now()
    )

    # Directories to ignore
    ignore_dirs = {
        '.git', 'node_modules', '__pycache__', '.venv', 'venv',
        '.next', 'dist', 'build', '.codeflow', '.worktrees',
        'coverage', '.nyc_output', '.pytest_cache', '.mypy_cache'
    }

    # Extensions to count
    code_extensions = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.vue', '.svelte',
        '.java', '.go', '.rs', '.rb', '.php', '.cs', '.cpp', '.c', '.h',
        '.html', '.css', '.scss', '.sass', '.less'
    }

    try:
        # Scan files and count lines
        for file_path in path.rglob("*"):
            if file_path.is_file():
                # Get relative path parts to check against ignore dirs
                try:
                    relative_parts = file_path.relative_to(path).parts
                except ValueError:
                    relative_parts = file_path.parts

                # Skip ignored directories
                if any(part in ignore_dirs for part in relative_parts):
                    continue

                # Count code files
                if file_path.suffix.lower() in code_extensions:
                    analysis.files_count += 1
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        analysis.lines_count += len(content.splitlines())
                    except Exception:
                        pass

        # Detect stack from package.json
        package_json = path / "package.json"
        if package_json.exists():
            try:
                pkg = json.loads(package_json.read_text(encoding="utf-8"))
                analysis.stack.append("node")
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

                if "react" in deps:
                    analysis.frameworks.append("react")
                if "next" in deps:
                    analysis.frameworks.append("nextjs")
                if "vue" in deps:
                    analysis.frameworks.append("vue")
                if "express" in deps:
                    analysis.frameworks.append("express")
                if "fastify" in deps:
                    analysis.frameworks.append("fastify")
                if "typescript" in deps:
                    analysis.stack.append("typescript")
            except Exception as e:
                logger.warning(f"Error reading package.json: {e}")

        # Detect Python stack
        requirements = path / "requirements.txt"
        pyproject = path / "pyproject.toml"

        if requirements.exists() or pyproject.exists():
            analysis.stack.append("python")

            req_content = ""
            if requirements.exists():
                try:
                    req_content = requirements.read_text(encoding="utf-8").lower()
                except Exception:
                    pass
            if pyproject.exists():
                try:
                    req_content += pyproject.read_text(encoding="utf-8").lower()
                except Exception:
                    pass

            if "fastapi" in req_content:
                analysis.frameworks.append("fastapi")
            if "django" in req_content:
                analysis.frameworks.append("django")
            if "flask" in req_content:
                analysis.frameworks.append("flask")

        # Detect Rust
        if (path / "Cargo.toml").exists():
            analysis.stack.append("rust")

        # Detect Go
        if (path / "go.mod").exists():
            analysis.stack.append("go")

        # Detect key directories
        key_dirs = [
            "src", "lib", "app", "components", "pages", "api",
            "backend", "frontend", "services", "utils", "models",
            "tests", "test", "__tests__", "spec"
        ]
        for dir_name in key_dirs:
            if (path / dir_name).is_dir():
                analysis.key_directories.append(dir_name)

        # Detect patterns
        patterns = []

        # Check for testing patterns
        if (path / "tests").is_dir() or (path / "test").is_dir() or (path / "__tests__").is_dir():
            patterns.append("unit_tests")
        if (path / "pytest.ini").exists() or (path / "conftest.py").exists():
            patterns.append("pytest")
        if (path / "jest.config.js").exists() or (path / "jest.config.ts").exists():
            patterns.append("jest")

        # Check for CI/CD
        if (path / ".github" / "workflows").is_dir():
            patterns.append("github_actions")
        if (path / ".gitlab-ci.yml").exists():
            patterns.append("gitlab_ci")
        if (path / "Dockerfile").exists():
            patterns.append("docker")
        if (path / "docker-compose.yml").exists() or (path / "docker-compose.yaml").exists():
            patterns.append("docker_compose")

        # Check for linting/formatting
        if (path / ".eslintrc.js").exists() or (path / ".eslintrc.json").exists():
            patterns.append("eslint")
        if (path / ".prettierrc").exists() or (path / ".prettierrc.json").exists():
            patterns.append("prettier")
        if (path / "pyproject.toml").exists():
            try:
                content = (path / "pyproject.toml").read_text(encoding="utf-8")
                if "ruff" in content:
                    patterns.append("ruff")
                if "black" in content:
                    patterns.append("black")
            except Exception:
                pass

        # Check for documentation
        if (path / "docs").is_dir():
            patterns.append("documentation")
        if (path / "README.md").exists():
            patterns.append("readme")

        analysis.patterns_detected = patterns

    except Exception as e:
        logger.error(f"Error analyzing project: {e}")

    # Save analysis
    storage = IdeationStorage(str(path))
    storage.save_analysis(analysis)

    return analysis


async def generate_suggestions(
    analysis: IdeationAnalysis,
    project_path: Optional[str] = None
) -> list[Suggestion]:
    """
    Generate improvement suggestions using Claude AI.

    Args:
        analysis: Project analysis data
        project_path: Path to project root

    Returns:
        List of suggestions
    """
    storage = IdeationStorage(project_path)

    # Build prompt with project context
    context = f"""Project: {analysis.project_name}
Stack: {', '.join(analysis.stack)}
Frameworks: {', '.join(analysis.frameworks)}
Files: {analysis.files_count} files, {analysis.lines_count} lines of code
Key directories: {', '.join(analysis.key_directories)}
Patterns detected: {', '.join(analysis.patterns_detected)}
"""

    system_prompt = """You are a senior software architect analyzing a project for improvements.
You MUST respond with ONLY a valid JSON array, no markdown, no explanations.
Each suggestion should be actionable and specific to the project."""

    prompt = f"""{context}

Analyze this project and suggest improvements in these categories:
- 🔒 security: validation, authentication, injection prevention, secrets management
- ⚡ performance: query optimization, caching, lazy loading, bundle size
- 📝 quality: tests, documentation, refactoring, code organization
- ✨ feature: missing functionality, developer experience improvements

Return 6-10 suggestions as a JSON array:
[{{"title": "string", "description": "string (2-3 sentences)", "category": "security|performance|quality|feature", "priority": "low|medium|high"}}]

Focus on specific, actionable suggestions based on the detected patterns and stack.
Respond with ONLY the JSON array:"""

    suggestions = []

    success, output, stderr = call_claude(
        prompt,
        timeout=120,
        json_output=True,
        system_prompt=system_prompt
    )

    if success and output:
        logger.info(f"Claude suggestions response: {len(output)} chars")
        data = extract_json_array(output)

        if data:
            for item in data:
                if isinstance(item, dict):
                    try:
                        category_str = item.get("category", "quality").lower()
                        category = SuggestionCategory(category_str)
                    except ValueError:
                        category = SuggestionCategory.QUALITY

                    suggestions.append(Suggestion(
                        id=generate_suggestion_id(),
                        title=item.get("title", "Untitled"),
                        description=item.get("description", ""),
                        category=category,
                        priority=item.get("priority", "medium"),
                        status=SuggestionStatus.PENDING,
                        created_at=datetime.now()
                    ))
            logger.info(f"Generated {len(suggestions)} suggestions")
        else:
            logger.warning(f"Failed to parse suggestions JSON: {output[:200]}")
    else:
        logger.warning(f"Claude call failed: {stderr}")
        # Generate fallback suggestions based on analysis
        suggestions = _generate_fallback_suggestions(analysis)

    # Save suggestions
    existing = storage.get_data().suggestions
    # Keep accepted/dismissed, replace pending
    kept = [s for s in existing if s.status != SuggestionStatus.PENDING]
    all_suggestions = kept + suggestions
    storage.save_suggestions(all_suggestions)

    return suggestions


def _generate_fallback_suggestions(analysis: IdeationAnalysis) -> list[Suggestion]:
    """Generate fallback suggestions when Claude is unavailable."""
    suggestions = []

    # Security suggestions
    if "fastapi" in analysis.frameworks or "express" in analysis.frameworks:
        suggestions.append(Suggestion(
            id=generate_suggestion_id(),
            title="Add input validation",
            description="Implement comprehensive input validation for all API endpoints using Pydantic models or Joi schemas to prevent injection attacks.",
            category=SuggestionCategory.SECURITY,
            priority="high"
        ))

    if "pytest" not in analysis.patterns_detected and "jest" not in analysis.patterns_detected:
        suggestions.append(Suggestion(
            id=generate_suggestion_id(),
            title="Add unit tests",
            description="Set up a testing framework and add unit tests for critical business logic to ensure code reliability.",
            category=SuggestionCategory.QUALITY,
            priority="high"
        ))

    if "docker" not in analysis.patterns_detected:
        suggestions.append(Suggestion(
            id=generate_suggestion_id(),
            title="Add Docker support",
            description="Create Dockerfile and docker-compose.yml for consistent development and deployment environments.",
            category=SuggestionCategory.QUALITY,
            priority="medium"
        ))

    if "github_actions" not in analysis.patterns_detected and "gitlab_ci" not in analysis.patterns_detected:
        suggestions.append(Suggestion(
            id=generate_suggestion_id(),
            title="Set up CI/CD pipeline",
            description="Configure automated testing and deployment pipeline using GitHub Actions or GitLab CI.",
            category=SuggestionCategory.QUALITY,
            priority="medium"
        ))

    if "documentation" not in analysis.patterns_detected:
        suggestions.append(Suggestion(
            id=generate_suggestion_id(),
            title="Add API documentation",
            description="Generate comprehensive API documentation using OpenAPI/Swagger for better developer experience.",
            category=SuggestionCategory.QUALITY,
            priority="medium"
        ))

    suggestions.append(Suggestion(
        id=generate_suggestion_id(),
        title="Implement caching strategy",
        description="Add caching layer for frequently accessed data to improve response times and reduce database load.",
        category=SuggestionCategory.PERFORMANCE,
        priority="medium"
    ))

    suggestions.append(Suggestion(
        id=generate_suggestion_id(),
        title="Add error monitoring",
        description="Integrate error monitoring service (Sentry, Rollbar) to track and alert on production errors.",
        category=SuggestionCategory.QUALITY,
        priority="medium"
    ))

    return suggestions


def _extract_suggestions_from_text(text: str) -> list[str]:
    """Extract actionable suggestions from AI response text."""
    suggestions = []
    lines = text.split('\n')

    # Look for common suggestion patterns
    suggestion_patterns = [
        "I suggest",
        "Consider",
        "You should",
        "You could",
        "I recommend",
        "Try",
        "Add",
        "Implement",
        "Create",
        "Update",
        "Use",
        "Set up",
        "Configure"
    ]

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check if line starts with bullet points or numbers
        if line.startswith(('-', '*', '•')) or (len(line) > 2 and line[0].isdigit() and line[1] in '.):'):
            # Extract the content after the marker
            content = line[2:].strip() if line.startswith(('-', '*', '•')) else line[line.index('.') + 1:].strip()
            if len(content) > 10:  # Reasonable length check
                suggestions.append(content)

        # Check for suggestion patterns at start of line
        elif any(line.startswith(pattern) for pattern in suggestion_patterns):
            if len(line) > 15:  # Reasonable length check
                suggestions.append(line)

    return suggestions[:5]  # Limit to 5 suggestions to avoid noise


async def chat_ideation(
    message: str,
    context: list[ChatMessage],
    project_path: Optional[str] = None
) -> tuple[str, list[str]]:
    """
    Brainstorm chat session with AI.

    Args:
        message: User message
        context: Previous chat messages
        project_path: Path to project root

    Returns:
        Tuple of (AI response, list of suggestions extracted)
    """
    storage = IdeationStorage(project_path)
    data = storage.get_data()

    # Build conversation context
    project_context = ""
    if data.analysis:
        project_context = f"""Project context:
- Name: {data.analysis.project_name}
- Stack: {', '.join(data.analysis.stack)}
- Frameworks: {', '.join(data.analysis.frameworks)}
- Size: {data.analysis.files_count} files, {data.analysis.lines_count} lines
"""

    # Build conversation history
    history = ""
    for msg in context[-10:]:  # Last 10 messages for context
        role = "Human" if msg.role == "user" else "Assistant"
        history += f"{role}: {msg.content}\n\n"

    system_prompt = """You are a helpful software architect having a brainstorming session.
Help the user think through ideas, suggest improvements, and discuss technical approaches.
Be conversational but informative. When you have concrete suggestions, mention them clearly.
If the user asks about specific implementations, provide code examples when helpful."""

    prompt = f"""{project_context}

Previous conversation:
{history}
Human: {message}

Please respond helpfully. If you have specific actionable suggestions, format them clearly."""

    success, output, stderr = call_claude(
        prompt,
        timeout=90,
        system_prompt=system_prompt
    )

    response = ""
    extracted_suggestions = []

    if success and output:
        response = output
        logger.info(f"Chat response: {len(response)} chars")

        # Extract suggestions from the response
        extracted_suggestions = _extract_suggestions_from_text(response)

    else:
        logger.warning(f"Chat Claude call failed: {stderr}")
        response = "I'm having trouble connecting to the AI service. Please try again in a moment."

    return response, extracted_suggestions


# Singleton storage instances
_storages: dict[str, IdeationStorage] = {}


def get_ideation_storage(project_path: Optional[str] = None) -> IdeationStorage:
    """Get or create storage instance for a project."""
    path = project_path or settings.project_path
    if path not in _storages:
        _storages[path] = IdeationStorage(path)
    return _storages[path]