"""
Changelog router - provides git log history for Codeflow commits.
"""
from fastapi import APIRouter, HTTPException, Query
import subprocess
import asyncio
import logging
import re
from datetime import datetime
from typing import Optional

from backend.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Regex patterns for task ID extraction
# Matches: [TASK-123], [task-456], #123, #456
TASK_ID_PATTERNS = [
    re.compile(r'\[TASK-(\d+)\]', re.IGNORECASE),  # [TASK-XXX] format
    re.compile(r'\[(\d+)\]'),                       # [XXX] format (number only)
    re.compile(r'#(\d+)(?!\d)'),                    # #XXX format (not followed by more digits)
]


def parse_commit_message(message: str) -> Optional[str]:
    """
    Extract task ID from a commit message.

    Supported formats:
    - [TASK-123] or [task-123] → returns "123"
    - [123] → returns "123"
    - #123 → returns "123"

    Returns the first task ID found, or None if no task ID is present.
    """
    if not message:
        return None

    for pattern in TASK_ID_PATTERNS:
        match = pattern.search(message)
        if match:
            return match.group(1)

    return None

# Pattern to identify Codeflow commits (Co-Authored-By: Claude)
CODEFLOW_COMMIT_PATTERN = "Co-Authored-By: Claude"


async def run_git_command(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    """Run a git command asynchronously."""
    return await asyncio.to_thread(
        subprocess.run,
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )


async def get_commit_files(commit_hash: str, cwd: str) -> list[str]:
    """Get list of files modified in a commit."""
    result = await run_git_command(
        ["show", "--name-only", "--format=", commit_hash],
        cwd
    )
    if result.returncode != 0:
        return []

    # Filter empty lines and return file list
    return [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]


async def get_commit_body(commit_hash: str, cwd: str) -> str:
    """Get the full body of a commit message."""
    result = await run_git_command(
        ["log", "-1", "--format=%b", commit_hash],
        cwd
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def is_codeflow_commit(body: str) -> bool:
    """Check if a commit was made by Codeflow (contains Co-Authored-By: Claude)."""
    return CODEFLOW_COMMIT_PATTERN in body


@router.get("/changelog")
async def get_changelog(
    limit: int = Query(default=50, ge=1, le=100, description="Maximum number of commits to return"),
    offset: int = Query(default=0, ge=0, description="Number of commits to skip"),
    codeflow_only: bool = Query(default=True, description="Only show Codeflow commits")
):
    """
    Get git log history, optionally filtered to Codeflow commits only.

    Returns a list of commits with:
    - hash: Commit hash (short)
    - full_hash: Full commit hash
    - date: ISO 8601 date string
    - message: Commit subject line
    - files: List of modified files
    - is_codeflow: Whether this is a Codeflow commit
    - task_id: Extracted task ID from message (e.g., "123" from "[TASK-123]" or "#123"), or null
    """
    try:
        # Get more commits than requested to account for filtering
        # We fetch 3x the limit to ensure we have enough after filtering
        fetch_limit = limit * 3 if codeflow_only else limit

        # Get commit list with hash, date, subject
        # Format: full_hash|short_hash|iso_date|subject
        result = await run_git_command(
            [
                "log",
                f"--skip={offset}",
                f"-{fetch_limit + offset}",  # Fetch enough to account for skip
                "--format=%H|%h|%aI|%s"
            ],
            settings.project_path
        )

        if result.returncode != 0:
            logger.error(f"Git log failed: {result.stderr}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get git log: {result.stderr}"
            )

        commits = []
        lines = [line for line in result.stdout.strip().split('\n') if line.strip()]

        for line in lines:
            if not line.strip():
                continue

            parts = line.split('|', 3)
            if len(parts) < 4:
                continue

            full_hash, short_hash, date_str, message = parts

            # Get commit body to check if it's a Codeflow commit
            body = await get_commit_body(full_hash, settings.project_path)
            is_codeflow = is_codeflow_commit(body)

            # Filter if codeflow_only is True
            if codeflow_only and not is_codeflow:
                continue

            # Get files modified in this commit
            files = await get_commit_files(full_hash, settings.project_path)

            # Extract task ID from commit message
            task_id = parse_commit_message(message)

            commits.append({
                "hash": short_hash,
                "full_hash": full_hash,
                "date": date_str,
                "message": message,
                "files": files,
                "is_codeflow": is_codeflow,
                "task_id": task_id
            })

            # Stop once we have enough commits
            if len(commits) >= limit:
                break

        return {
            "commits": commits,
            "count": len(commits),
            "has_more": len(lines) > len(commits)
        }

    except subprocess.CalledProcessError as e:
        logger.error(f"Git command failed: {e}")
        raise HTTPException(status_code=500, detail=f"Git command failed: {str(e)}")
    except Exception as e:
        logger.error(f"Error getting changelog: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting changelog: {str(e)}")
