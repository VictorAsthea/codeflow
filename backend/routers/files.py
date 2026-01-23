from fastapi import APIRouter, Query
from pathlib import Path
from typing import List
import os

router = APIRouter()


@router.get("/files/list")
async def list_project_files(
    pattern: str = Query("**/*", description="Glob pattern"),
    exclude: List[str] = Query(default=[
        "**/.git/**", "**/node_modules/**", "**/__pycache__/**",
        "**/.venv/**", "**/dist/**", "**/build/**", "**/.worktrees/**",
        "**/venv/**", "**/.env", "**/*.pyc", "**/.DS_Store"
    ])
):
    """List files matching pattern from project directory"""
    from backend.config import settings

    project_path = Path(settings.project_path)

    if not project_path.exists():
        return []

    files = []
    try:
        for path in project_path.glob(pattern):
            if path.is_file():
                try:
                    rel_path = str(path.relative_to(project_path))

                    should_exclude = False
                    for ex_pattern in exclude:
                        ex_pattern_clean = ex_pattern.replace("**/", "").replace("/**", "")
                        if ex_pattern_clean in rel_path or path.match(ex_pattern):
                            should_exclude = True
                            break

                    if not should_exclude:
                        files.append({
                            "path": rel_path.replace("\\", "/"),
                            "name": path.name,
                            "size": path.stat().st_size
                        })

                        if len(files) >= 100:
                            break
                except (ValueError, OSError):
                    continue
    except Exception as e:
        print(f"[ERROR] Failed to list files: {e}")
        return []

    return files


@router.get("/files/search")
async def search_files(q: str = Query(..., min_length=1)):
    """Search files by name in project directory"""
    from backend.config import settings

    project_path = Path(settings.project_path)

    if not project_path.exists():
        return []

    q_lower = q.lower()
    results = []

    excluded_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'dist', 'build', '.worktrees', 'venv'}

    try:
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in excluded_dirs]

            for file in files:
                if q_lower in file.lower():
                    full_path = Path(root) / file
                    try:
                        rel_path = str(full_path.relative_to(project_path))
                        results.append({
                            "path": rel_path.replace("\\", "/"),
                            "name": file
                        })

                        if len(results) >= 50:
                            return results
                    except (ValueError, OSError):
                        continue
    except Exception as e:
        print(f"[ERROR] Failed to search files: {e}")
        return []

    return results
