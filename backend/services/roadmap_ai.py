"""
AI-powered roadmap analysis and feature generation.

Uses Claude to analyze projects, discover competitors, and generate feature suggestions.
"""

import subprocess
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Any
import logging

from backend.models import (
    Feature,
    ProjectAnalysis,
    CompetitorAnalysis,
    Competitor,
    Priority,
    RoadmapPhase,
    Complexity,
    Impact,
    FeatureStatus,
)
from backend.config import settings

logger = logging.getLogger(__name__)


def generate_feature_id() -> str:
    """Generate a unique feature ID."""
    import uuid
    return f"feat-{uuid.uuid4().hex[:8]}"


def extract_json_array(text: str) -> list[dict] | None:
    """
    Extract JSON array from text that may contain markdown or other content.

    Handles cases like:
    - Pure JSON array
    - JSON wrapped in markdown code blocks
    - JSON with leading/trailing text
    """
    if not text:
        return None

    # Remove markdown code blocks if present
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()

    # Try direct parse first
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # Try to find JSON array with regex (handles nested objects)
    # Match from first [ to last ]
    bracket_match = re.search(r'\[[\s\S]*\]', text)
    if bracket_match:
        try:
            data = json.loads(bracket_match.group())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    # Try line by line to find valid JSON
    lines = text.split('\n')
    json_lines = []
    in_json = False
    bracket_count = 0

    for line in lines:
        if '[' in line and not in_json:
            in_json = True
        if in_json:
            json_lines.append(line)
            bracket_count += line.count('[') - line.count(']')
            if bracket_count <= 0 and ']' in line:
                break

    if json_lines:
        try:
            data = json.loads('\n'.join(json_lines))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    return None


def get_claude_command() -> str:
    """
    Get the Claude CLI command path.

    Checks multiple locations for Claude CLI installation.
    """
    import shutil
    import os

    # Check if claude is in PATH
    claude_path = shutil.which("claude")
    if claude_path:
        return claude_path

    # Common installation locations
    possible_paths = [
        # npm global install (Windows)
        os.path.expandvars(r"%APPDATA%\npm\claude.cmd"),
        os.path.expandvars(r"%APPDATA%\npm\claude"),
        # npm global install (Unix)
        os.path.expanduser("~/.npm-global/bin/claude"),
        "/usr/local/bin/claude",
        "/usr/bin/claude",
        # pnpm
        os.path.expanduser("~/.local/share/pnpm/claude"),
    ]

    for path in possible_paths:
        if os.path.exists(path):
            logger.info(f"Found Claude CLI at: {path}")
            return path

    return "claude"  # Fallback to hoping it's in PATH


def call_claude(
    prompt: str,
    timeout: int = 120,
    json_output: bool = False,
    system_prompt: str | None = None
) -> tuple[bool, str, str]:
    """
    Call Claude CLI with a prompt.

    Args:
        prompt: The prompt to send
        timeout: Timeout in seconds
        json_output: If True, use --output-format json
        system_prompt: Optional system prompt to override default

    Returns:
        Tuple of (success, stdout, stderr)
    """
    import os

    claude_cmd = get_claude_command()

    try:
        # Build command - note: prompt is passed via stdin for long prompts
        # -p/--print enables non-interactive mode
        cmd = [claude_cmd, "--print"]

        if json_output:
            cmd.extend(["--output-format", "json"])

        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        # Tell Claude CLI to read prompt from stdin
        cmd.append("-")

        logger.info(f"Calling Claude CLI: {claude_cmd} (timeout={timeout}s, json={json_output})...")
        logger.debug(f"Command: {' '.join(cmd[:4])}... [stdin]")

        # Prepare environment with npm path
        env = os.environ.copy()
        npm_path = os.path.expandvars(r"%APPDATA%\npm")
        if os.path.exists(npm_path):
            env["PATH"] = npm_path + os.pathsep + env.get("PATH", "")

        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=settings.project_path,
            timeout=timeout,
            env=env
        )

        logger.info(f"Claude return code: {result.returncode}")
        if result.stderr:
            logger.warning(f"Claude stderr: {result.stderr[:200]}")

        output = result.stdout.strip()

        # If json output, try to extract the result field
        if json_output and output:
            try:
                data = json.loads(output)
                # Claude CLI json format has a "result" field with the actual content
                if isinstance(data, dict) and "result" in data:
                    output = data["result"]
                    logger.info(f"Extracted result from JSON response ({len(output)} chars)")
            except json.JSONDecodeError:
                pass

        if output:
            logger.info(f"Claude output length: {len(output)}")
            logger.debug(f"Claude output preview: {output[:300]}...")

        return result.returncode == 0, output, result.stderr

    except subprocess.TimeoutExpired:
        logger.error(f"Claude CLI timed out after {timeout}s")
        return False, "", "Timeout"
    except FileNotFoundError:
        logger.error(f"Claude CLI not found at {claude_cmd}. Make sure it's installed.")
        return False, "", "Claude CLI not found"
    except Exception as e:
        logger.error(f"Error calling Claude: {e}")
        return False, "", str(e)


async def extract_project_info(project_path: Path | None = None) -> dict:
    """
    Extract project information by reading project files directly.
    Uses simple parsing first, Claude as enhancement.

    Returns dict with: project_name, description, target_audience
    """
    if project_path is None:
        project_path = Path(settings.project_path)

    folder_name = project_path.name
    project_name = folder_name
    description = ""
    target_audience = "Developers"

    # Try to get name from package.json
    pkg_path = project_path / "package.json"
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text(encoding='utf-8', errors='ignore'))
            if pkg.get("name"):
                project_name = pkg["name"]
            if pkg.get("description"):
                description = pkg["description"]
        except Exception:
            pass

    # Try to get from pyproject.toml
    pyproject_path = project_path / "pyproject.toml"
    if pyproject_path.exists() and not description:
        try:
            content = pyproject_path.read_text(encoding='utf-8', errors='ignore')
            # Simple parsing for name and description
            for line in content.split('\n'):
                if line.startswith('name = '):
                    project_name = line.split('=')[1].strip().strip('"\'')
                if line.startswith('description = '):
                    description = line.split('=', 1)[1].strip().strip('"\'')
        except Exception:
            pass

    # Try to get description from README
    if not description:
        for readme_name in ["README.md", "readme.md", "README.rst", "README.txt"]:
            readme_path = project_path / readme_name
            if readme_path.exists():
                try:
                    content = readme_path.read_text(encoding='utf-8', errors='ignore')
                    lines = content.split('\n')
                    # Skip title lines, get first paragraph
                    desc_lines = []
                    for line in lines:
                        line = line.strip()
                        if not line:
                            if desc_lines:
                                break
                            continue
                        if line.startswith('#') or line.startswith('![') or line.startswith('[!'):
                            continue
                        if line.startswith('**') and line.endswith('**'):
                            # This might be a tagline
                            description = line.strip('*').strip()
                            break
                        desc_lines.append(line)
                    if desc_lines and not description:
                        description = ' '.join(desc_lines)[:200]
                except Exception:
                    pass
                break

    # Fallback description
    if not description:
        description = f"A software project built with modern technologies"

    return {
        "project_name": project_name,
        "description": description,
        "target_audience": target_audience
    }


def scan_codebase_deep(project_path: Path) -> dict:
    """
    Deep scan of the codebase to understand the project structure.

    Returns a dict with:
    - directory_tree: Folder structure (max 3 levels)
    - key_files: List of important files found
    - file_samples: Content excerpts from key files
    - patterns: Detected patterns (tests, CI, docker, etc.)
    - endpoints: Detected API endpoints (if any)
    - components: Detected UI components (if any)
    """
    EXCLUDED_DIRS = {
        '.git', 'node_modules', '__pycache__', '.venv', 'venv',
        'dist', 'build', '.worktrees', '.next', '.nuxt', 'coverage',
        '.pytest_cache', '.mypy_cache', 'eggs', '*.egg-info'
    }

    EXCLUDED_EXTENSIONS = {'.pyc', '.pyo', '.ico', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.woff', '.woff2', '.ttf', '.eot'}

    KEY_FILE_PATTERNS = [
        # Entry points
        'main.py', 'app.py', 'index.py', 'server.py', '__init__.py',
        'main.ts', 'main.js', 'index.ts', 'index.js', 'app.ts', 'app.js',
        'main.go', 'main.rs',
        # Config
        'package.json', 'pyproject.toml', 'requirements.txt', 'Cargo.toml', 'go.mod',
        'tsconfig.json', 'vite.config.ts', 'next.config.js', 'webpack.config.js',
        # API/Routes
        'routes.py', 'urls.py', 'api.py', 'router.py', 'endpoints.py',
        'routes.ts', 'routes.js', 'api.ts', 'api.js',
        # Models/Schema
        'models.py', 'schema.py', 'schemas.py', 'types.ts', 'types.py',
        # Database
        'database.py', 'db.py', 'migrations.py',
        # Components (frontend)
        'App.tsx', 'App.jsx', 'App.vue', 'App.svelte',
    ]

    KEY_DIRECTORIES = ['routers', 'routes', 'api', 'endpoints', 'controllers', 'views', 'components', 'pages', 'services', 'models', 'schemas']

    result = {
        'directory_tree': [],
        'key_files': [],
        'file_samples': {},
        'patterns': [],
        'endpoints': [],
        'components': [],
        'services': [],
    }

    def should_exclude(path: Path) -> bool:
        for part in path.parts:
            if part in EXCLUDED_DIRS or part.startswith('.'):
                return True
        if path.suffix.lower() in EXCLUDED_EXTENSIONS:
            return True
        return False

    # Build directory tree (max 3 levels)
    def build_tree(path: Path, prefix: str = "", level: int = 0) -> list[str]:
        if level > 3 or should_exclude(path):
            return []

        tree = []
        try:
            items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            dirs = [i for i in items if i.is_dir() and not should_exclude(i)]
            files = [i for i in items if i.is_file() and not should_exclude(i)]

            # Limit items per level
            for d in dirs[:10]:
                tree.append(f"{prefix}{d.name}/")
                tree.extend(build_tree(d, prefix + "  ", level + 1))

            for f in files[:15]:
                tree.append(f"{prefix}{f.name}")
        except PermissionError:
            pass

        return tree

    result['directory_tree'] = build_tree(project_path)

    # Find key files
    all_files = []
    try:
        for path in project_path.rglob("*"):
            if path.is_file() and not should_exclude(path):
                all_files.append(path)
    except Exception:
        pass

    # Identify key files
    for file_path in all_files:
        rel_path = file_path.relative_to(project_path)
        rel_str = str(rel_path).replace('\\', '/')

        # Check if it's a key file by name
        if file_path.name in KEY_FILE_PATTERNS:
            result['key_files'].append(rel_str)

        # Check if it's in a key directory
        for key_dir in KEY_DIRECTORIES:
            if f"/{key_dir}/" in f"/{rel_str}" or rel_str.startswith(f"{key_dir}/"):
                result['key_files'].append(rel_str)
                break

    # Remove duplicates and limit
    result['key_files'] = list(set(result['key_files']))[:30]

    # Read samples from key files (first 40 lines)
    for rel_path in result['key_files'][:15]:
        file_path = project_path / rel_path
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            lines = content.split('\n')[:40]
            result['file_samples'][rel_path] = '\n'.join(lines)
        except Exception:
            pass

    # Detect patterns
    patterns = []

    # Tests
    if any('test' in str(f).lower() for f in all_files):
        patterns.append('Tests (unit/integration)')
    if (project_path / 'pytest.ini').exists() or (project_path / 'conftest.py').exists():
        patterns.append('Pytest')
    if (project_path / 'jest.config.js').exists() or (project_path / 'jest.config.ts').exists():
        patterns.append('Jest')

    # CI/CD
    if (project_path / '.github' / 'workflows').exists():
        patterns.append('GitHub Actions CI/CD')
    if (project_path / '.gitlab-ci.yml').exists():
        patterns.append('GitLab CI')
    if (project_path / 'Jenkinsfile').exists():
        patterns.append('Jenkins CI')

    # Docker
    if (project_path / 'Dockerfile').exists() or (project_path / 'docker-compose.yml').exists():
        patterns.append('Docker')

    # Database
    if any('alembic' in str(f).lower() for f in all_files):
        patterns.append('Alembic migrations')
    if any('prisma' in str(f).lower() for f in all_files):
        patterns.append('Prisma ORM')
    if any('sequelize' in str(f).lower() for f in all_files):
        patterns.append('Sequelize ORM')

    # API patterns
    if any('swagger' in str(f).lower() or 'openapi' in str(f).lower() for f in all_files):
        patterns.append('OpenAPI/Swagger')
    if any('graphql' in str(f).lower() for f in all_files):
        patterns.append('GraphQL')

    result['patterns'] = patterns

    # Detect API endpoints from router files
    for rel_path, content in result['file_samples'].items():
        if any(kw in rel_path.lower() for kw in ['router', 'route', 'api', 'endpoint', 'controller']):
            # Python FastAPI/Flask patterns
            for line in content.split('\n'):
                if '@router.' in line or '@app.' in line or '@blueprint.' in line:
                    # Extract method and path
                    if any(method in line for method in ['.get(', '.post(', '.put(', '.delete(', '.patch(']):
                        result['endpoints'].append(line.strip())
                # Express.js patterns
                if 'router.' in line.lower() and any(m in line.lower() for m in ['get(', 'post(', 'put(', 'delete(']):
                    result['endpoints'].append(line.strip())

    result['endpoints'] = result['endpoints'][:20]

    # Detect components from frontend files
    for rel_path in result['key_files']:
        if 'component' in rel_path.lower() or rel_path.endswith(('.tsx', '.jsx', '.vue', '.svelte')):
            result['components'].append(rel_path)

    result['components'] = result['components'][:15]

    # Detect services
    for rel_path in result['key_files']:
        if 'service' in rel_path.lower():
            result['services'].append(rel_path)

    result['services'] = result['services'][:10]

    return result


async def analyze_project(project_path: Path | None = None) -> ProjectAnalysis:
    """
    Analyze the project structure and detect stack.

    Args:
        project_path: Path to project root

    Returns:
        ProjectAnalysis with detected info
    """
    if project_path is None:
        project_path = Path(settings.project_path)

    stack = []
    files_count = 0
    structure_summary = ""

    # Count files and detect stack
    try:
        # Get file count
        for path in project_path.rglob("*"):
            if path.is_file() and not any(
                part.startswith('.') or part == 'node_modules' or part == '__pycache__' or part == 'venv'
                for part in path.parts
            ):
                files_count += 1

        # Detect stack from common files
        if (project_path / "package.json").exists():
            stack.append("Node.js")
            try:
                pkg = json.loads((project_path / "package.json").read_text())
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "react" in deps:
                    stack.append("React")
                if "vue" in deps:
                    stack.append("Vue")
                if "next" in deps:
                    stack.append("Next.js")
                if "typescript" in deps:
                    stack.append("TypeScript")
                if "express" in deps:
                    stack.append("Express.js")
                if "fastify" in deps:
                    stack.append("Fastify")
                if "tailwindcss" in deps:
                    stack.append("Tailwind CSS")
            except Exception:
                pass

        if (project_path / "requirements.txt").exists() or (project_path / "pyproject.toml").exists():
            stack.append("Python")
            # Check for frameworks
            req_content = ""
            if (project_path / "requirements.txt").exists():
                req_content = (project_path / "requirements.txt").read_text(errors='ignore').lower()
            if (project_path / "pyproject.toml").exists():
                req_content += (project_path / "pyproject.toml").read_text(errors='ignore').lower()

            if "fastapi" in req_content:
                stack.append("FastAPI")
            if "django" in req_content:
                stack.append("Django")
            if "flask" in req_content:
                stack.append("Flask")
            if "sqlalchemy" in req_content:
                stack.append("SQLAlchemy")

        if (project_path / "Cargo.toml").exists():
            stack.append("Rust")

        if (project_path / "go.mod").exists():
            stack.append("Go")

        # Read README for summary
        readme_path = None
        for name in ["README.md", "readme.md", "README.rst", "README.txt"]:
            if (project_path / name).exists():
                readme_path = project_path / name
                break

        if readme_path:
            readme_content = readme_path.read_text(encoding='utf-8', errors='ignore')[:2000]
            # Extract first paragraph as summary
            lines = readme_content.split('\n')
            summary_lines = []
            for line in lines:
                if line.startswith('#'):
                    continue
                if line.strip():
                    summary_lines.append(line.strip())
                    if len(summary_lines) >= 3:
                        break
            structure_summary = ' '.join(summary_lines)[:500]

    except Exception as e:
        structure_summary = f"Error analyzing project: {str(e)}"

    return ProjectAnalysis(
        date=datetime.now(),
        stack=stack,
        structure_summary=structure_summary,
        files_count=files_count
    )


async def discover_competitors(
    project_name: str,
    project_description: str,
    existing_competitors: list[Competitor] | None = None
) -> CompetitorAnalysis:
    """
    Discover competitor products using Claude.

    Args:
        project_name: Name of the project
        project_description: Project description
        existing_competitors: Optional existing competitors to augment

    Returns:
        CompetitorAnalysis with discovered competitors
    """
    competitors = list(existing_competitors or [])

    system_prompt = """You are a product analyst AI that outputs ONLY valid JSON arrays.
You MUST respond with ONLY a JSON array, no markdown, no explanations."""

    prompt = f"""Project: {project_name}
Description: {project_description}

List 3-5 competing products/tools. Return JSON array:
[{{"name": "string", "url": "string or null", "features": ["feature1", "feature2"]}}]

Respond with ONLY the JSON array:"""

    success, output, stderr = call_claude(
        prompt,
        timeout=90,
        json_output=True,
        system_prompt=system_prompt
    )

    if success and output:
        logger.info(f"Discover competitors response: {len(output)} chars")

        data = extract_json_array(output)
        if data:
            logger.info(f"Found {len(data)} competitors")
            for item in data:
                if isinstance(item, dict):
                    competitors.append(Competitor(
                        name=item.get("name", "Unknown"),
                        url=item.get("url"),
                        features=item.get("features", [])
                    ))
        else:
            logger.warning(f"Failed to parse competitors JSON: {output[:200]}")
    else:
        logger.warning(f"Discover competitors failed: {stderr}")

    return CompetitorAnalysis(
        date=datetime.now(),
        competitors=competitors
    )


def get_fallback_features(
    project_name: str,
    stack: list[str],
    project_description: str
) -> list[dict]:
    """
    Generate fallback features based on project type when Claude is unavailable.
    """
    features = []

    # Common features for all projects
    common_features = [
        {
            "title": "User Authentication",
            "description": "Implement secure user authentication with login, logout, and session management.",
            "justification": "Essential for user management and security.",
            "phase": "foundation",
            "priority": "must",
            "complexity": "medium",
            "impact": "high"
        },
        {
            "title": "Error Handling & Logging",
            "description": "Comprehensive error handling with structured logging for debugging and monitoring.",
            "justification": "Critical for maintaining production stability and debugging issues.",
            "phase": "foundation",
            "priority": "must",
            "complexity": "low",
            "impact": "high"
        },
        {
            "title": "API Documentation",
            "description": "Auto-generated API documentation with interactive examples.",
            "justification": "Improves developer experience and onboarding.",
            "phase": "core",
            "priority": "should",
            "complexity": "low",
            "impact": "medium"
        },
        {
            "title": "Configuration Management",
            "description": "Centralized configuration with environment-based settings.",
            "justification": "Enables easy deployment across environments.",
            "phase": "foundation",
            "priority": "must",
            "complexity": "low",
            "impact": "medium"
        },
        {
            "title": "Performance Optimization",
            "description": "Implement caching, lazy loading, and query optimization.",
            "justification": "Improves user experience and reduces server costs.",
            "phase": "enhancement",
            "priority": "should",
            "complexity": "medium",
            "impact": "high"
        },
        {
            "title": "Automated Testing",
            "description": "Unit tests, integration tests, and end-to-end testing setup.",
            "justification": "Ensures code quality and prevents regressions.",
            "phase": "core",
            "priority": "must",
            "complexity": "medium",
            "impact": "high"
        },
        {
            "title": "CI/CD Pipeline",
            "description": "Automated build, test, and deployment workflow.",
            "justification": "Speeds up development and ensures consistent deployments.",
            "phase": "core",
            "priority": "should",
            "complexity": "medium",
            "impact": "high"
        },
        {
            "title": "User Dashboard",
            "description": "Central dashboard for users to view and manage their data.",
            "justification": "Core user interface for the application.",
            "phase": "core",
            "priority": "must",
            "complexity": "medium",
            "impact": "high"
        },
        {
            "title": "Dark Mode Support",
            "description": "Implement dark mode theme with user preference persistence.",
            "justification": "Improves accessibility and user experience.",
            "phase": "polish",
            "priority": "could",
            "complexity": "low",
            "impact": "low"
        },
        {
            "title": "Export & Import Data",
            "description": "Allow users to export and import their data in common formats.",
            "justification": "Gives users control over their data.",
            "phase": "enhancement",
            "priority": "could",
            "complexity": "medium",
            "impact": "medium"
        }
    ]

    # Add Python/FastAPI specific features
    if "Python" in stack or "FastAPI" in stack:
        features.extend([
            {
                "title": "Database Migrations",
                "description": "Alembic-based database schema migrations for safe upgrades.",
                "justification": "Essential for evolving the data model safely.",
                "phase": "foundation",
                "priority": "must",
                "complexity": "low",
                "impact": "high"
            },
            {
                "title": "Background Tasks",
                "description": "Async task queue for long-running operations.",
                "justification": "Prevents blocking the main application.",
                "phase": "enhancement",
                "priority": "should",
                "complexity": "medium",
                "impact": "medium"
            }
        ])

    # Add frontend specific features
    if "React" in stack or "Vue" in stack or "Node.js" in stack:
        features.extend([
            {
                "title": "State Management",
                "description": "Centralized state management for complex UI interactions.",
                "justification": "Improves maintainability of frontend code.",
                "phase": "core",
                "priority": "should",
                "complexity": "medium",
                "impact": "medium"
            },
            {
                "title": "Responsive Design",
                "description": "Mobile-first responsive layout for all screen sizes.",
                "justification": "Essential for modern web applications.",
                "phase": "core",
                "priority": "must",
                "complexity": "medium",
                "impact": "high"
            }
        ])

    # Add common features and limit to 10
    features.extend(common_features)
    return features[:10]


async def generate_features(
    project_name: str,
    project_description: str,
    target_audience: str,
    analysis: ProjectAnalysis | None = None,
    competitor_analysis: CompetitorAnalysis | None = None,
    existing_features: list[Feature] | None = None,
    project_path: Path | None = None
) -> list[Feature]:
    """
    Generate feature suggestions using Claude with deep codebase analysis.

    Args:
        project_name: Name of the project
        project_description: Project description
        target_audience: Target audience description
        analysis: Project analysis data
        competitor_analysis: Competitor analysis data
        existing_features: Existing features to avoid duplicates
        project_path: Path to project for deep scanning

    Returns:
        List of suggested features
    """
    existing_titles = {f.title.lower() for f in (existing_features or [])}
    stack = analysis.stack if analysis else []

    # Perform deep codebase scan
    if project_path is None:
        project_path = Path(settings.project_path)

    codebase_scan = scan_codebase_deep(project_path)

    # Build rich context for Claude
    context = f"""# Analyse du projet: {project_name}

## Description
{project_description}

## Public cible
{target_audience}

## Stack technique
{', '.join(analysis.stack) if analysis else 'Non détecté'}

## Taille du projet
{analysis.files_count if analysis else 0} fichiers

## Structure du projet
```
{chr(10).join(codebase_scan['directory_tree'][:50])}
```

## Fichiers clés identifiés
{chr(10).join('- ' + f for f in codebase_scan['key_files'][:20])}

## Patterns détectés
{chr(10).join('- ' + p for p in codebase_scan['patterns']) if codebase_scan['patterns'] else 'Aucun pattern spécifique détecté'}

## Endpoints API existants
{chr(10).join('- ' + e for e in codebase_scan['endpoints'][:15]) if codebase_scan['endpoints'] else 'Aucun endpoint détecté'}

## Services backend
{chr(10).join('- ' + s for s in codebase_scan['services'][:10]) if codebase_scan['services'] else 'Aucun service détecté'}

## Composants frontend
{chr(10).join('- ' + c for c in codebase_scan['components'][:10]) if codebase_scan['components'] else 'Aucun composant détecté'}
"""

    # Add code samples from key files (limit to avoid token overflow)
    code_samples = ""
    samples_added = 0
    for file_path, content in list(codebase_scan['file_samples'].items())[:8]:
        if samples_added >= 3000:  # Limit total code samples
            break
        sample = content[:500]  # First 500 chars of each file
        code_samples += f"\n### {file_path}\n```\n{sample}\n```\n"
        samples_added += len(sample)

    if code_samples:
        context += f"\n## Extraits de code clés\n{code_samples}"

    # Add competitors if available
    if competitor_analysis and competitor_analysis.competitors:
        context += "\n## Concurrents identifiés\n"
        for comp in competitor_analysis.competitors:
            context += f"- **{comp.name}**: {', '.join(comp.features[:3])}\n"

    # Add existing features to avoid duplicates
    if existing_features:
        context += f"\n## Fonctionnalités existantes (à ne pas dupliquer)\n"
        context += '\n'.join(f"- {f.title}" for f in existing_features[:10])

    system_prompt = """Tu es un expert en product management et architecture logicielle.
Tu analyses des projets en profondeur pour suggérer des fonctionnalités pertinentes.

IMPORTANT:
- Tes suggestions doivent être SPÉCIFIQUES au projet analysé
- Ne propose PAS de fonctionnalités génériques qui existent déjà (regarde les endpoints, services, composants)
- Propose des améliorations concrètes basées sur ce que tu vois dans le code
- Priorise les fonctionnalités qui apportent de la valeur aux utilisateurs

Tu dois répondre UNIQUEMENT avec un tableau JSON valide, sans markdown, sans explication."""

    prompt = f"""{context}

---

En te basant sur cette analyse approfondie du codebase, génère 8-10 suggestions de fonctionnalités PERTINENTES et SPÉCIFIQUES à ce projet.

Pour chaque fonctionnalité, fournis:
- title: string (nom court et clair)
- description: string (1-2 phrases décrivant la fonctionnalité)
- justification: string (pourquoi c'est important pour ce projet spécifiquement)
- phase: "foundation" | "core" | "enhancement" | "polish"
- priority: "must" | "should" | "could" | "wont"
- complexity: "low" | "medium" | "high"
- impact: "low" | "medium" | "high"

Réponds UNIQUEMENT avec le tableau JSON:"""

    features = []
    data = []

    # Try to call Claude with system prompt that enforces JSON
    success, output, stderr = call_claude(
        prompt,
        timeout=180,
        json_output=True,
        system_prompt=system_prompt
    )

    if success and output:
        logger.info(f"Claude responded with {len(output)} characters")
        logger.info(f"Output preview: {output[:500]}")

        # Extract JSON from response
        data = extract_json_array(output)
        if data:
            logger.info(f"Extracted {len(data)} features from Claude response")
        else:
            logger.warning(f"Failed to extract JSON from Claude response")
            logger.warning(f"Full output: {output}")
    else:
        logger.warning(f"Claude call failed: {stderr}")

    # Use fallback features if Claude didn't work
    if not data:
        logger.info("Using fallback features")
        data = get_fallback_features(project_name, stack, project_description)

    # Convert to Feature models
    for item in data:
        if not isinstance(item, dict):
            continue

        title = item.get("title", "")
        if not title or title.lower() in existing_titles:
            continue

        try:
            features.append(Feature(
                id=generate_feature_id(),
                title=title,
                description=item.get("description", ""),
                justification=item.get("justification"),
                phase=RoadmapPhase(item.get("phase", "core")),
                priority=Priority(item.get("priority", "should")),
                complexity=Complexity(item.get("complexity", "medium")),
                impact=Impact(item.get("impact", "medium")),
                status=FeatureStatus.UNDER_REVIEW,
                created_at=datetime.now(),
                updated_at=datetime.now()
            ))
        except Exception as e:
            logger.warning(f"Failed to create feature from {item}: {e}")

    logger.info(f"Generated {len(features)} features total")
    return features


async def expand_feature_description(feature: Feature) -> str:
    """
    Generate expanded description for a feature.

    Args:
        feature: Feature to expand

    Returns:
        Expanded description
    """
    prompt = f"""Expand this feature description into a detailed specification:

Title: {feature.title}
Description: {feature.description}
Justification: {feature.justification or 'Not provided'}

Provide:
1. Detailed user story
2. Acceptance criteria (3-5 points)
3. Technical considerations

Keep it concise but comprehensive. Return plain text, not JSON."""

    success, output, stderr = call_claude(prompt, timeout=60)

    if success and output:
        return output

    logger.warning(f"Failed to expand feature: {stderr}")
    return feature.description
