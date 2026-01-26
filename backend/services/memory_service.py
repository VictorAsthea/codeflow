"""
Service for reading Claude Code session history.
Parses session data from ~/.claude/projects/{project}/sessions-index.json
and individual session .jsonl files.
"""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.models import ClaudeSession, SessionDetail, SessionMessage

logger = logging.getLogger(__name__)


def _normalize_project_path(path: str) -> str:
    """
    Convert a project path to Claude's folder naming convention.
    Example: C:\\Users\\victo\\Documents\\DEV\\Codeflow -> C--Users-victo-Documents-DEV-Codeflow

    Claude's convention:
    - Drive letter followed by double dash (C:\\ -> C--)
    - Path separators become single dash
    - .worktrees becomes -worktrees-
    """
    # Normalize path separators to forward slash first
    normalized = path.replace("\\", "/")

    # Handle Windows drive letter (C:/ -> C--)
    if len(normalized) >= 2 and normalized[1] == ":":
        drive = normalized[0]
        rest = normalized[2:].lstrip("/")
        normalized = f"{drive}--{rest}"

    # Replace remaining path separators with dashes
    normalized = normalized.replace("/", "-")

    # Handle dots in path (like .worktrees)
    normalized = normalized.replace(".", "")

    return normalized


def _get_claude_projects_dir() -> Path:
    """Get the Claude projects directory path."""
    home = Path.home()
    return home / ".claude" / "projects"


def _extract_task_id_from_path(path: str) -> Optional[str]:
    """
    Extract task ID from a worktree path.
    Example: .worktrees/042-auth-feature -> 042
    """
    match = re.search(r"[/\\]\.?worktrees?[/\\](\d{3})-", path)
    if match:
        return match.group(1)
    return None


def _parse_iso_datetime(dt_string: str) -> datetime:
    """Parse ISO datetime string, handling various formats."""
    try:
        # Handle ISO format with Z suffix
        if dt_string.endswith("Z"):
            dt_string = dt_string[:-1] + "+00:00"
        return datetime.fromisoformat(dt_string)
    except ValueError:
        return datetime.now()


class MemoryService:
    """Service for accessing Claude Code session history."""

    def __init__(self):
        self._projects_dir = _get_claude_projects_dir()

    def _get_project_sessions_dir(self, project_path: str) -> Optional[Path]:
        """Get the Claude sessions directory for a specific project."""
        normalized = _normalize_project_path(project_path)
        project_dir = self._projects_dir / normalized
        if project_dir.exists():
            return project_dir
        return None

    def _find_matching_projects(self, project_path: str) -> list[Path]:
        """
        Find all Claude project directories that match the given project path.
        This includes the main project and all worktrees.
        """
        if not self._projects_dir.exists():
            return []

        # Normalize the base project path (without worktree suffix)
        base_path = project_path
        if ".worktrees" in project_path:
            base_path = project_path.split(".worktrees")[0].rstrip("/\\")

        normalized_base = _normalize_project_path(base_path)
        matching_dirs = []

        for entry in self._projects_dir.iterdir():
            if entry.is_dir():
                entry_name = entry.name
                # Match exact project or worktrees of the project
                if entry_name == normalized_base or entry_name.startswith(normalized_base + "-"):
                    matching_dirs.append(entry)

        return matching_dirs

    def get_sessions(
        self,
        project_path: str,
        include_worktrees: bool = True,
        limit: int = 50
    ) -> list[ClaudeSession]:
        """
        Get all Claude Code sessions for a project.

        Args:
            project_path: Path to the project
            include_worktrees: If True, include sessions from project worktrees
            limit: Maximum number of sessions to return

        Returns:
            List of ClaudeSession objects, sorted by modification date (newest first)
        """
        sessions: list[ClaudeSession] = []

        if include_worktrees:
            project_dirs = self._find_matching_projects(project_path)
        else:
            project_dir = self._get_project_sessions_dir(project_path)
            project_dirs = [project_dir] if project_dir else []

        for project_dir in project_dirs:
            sessions.extend(self._load_sessions_from_index(project_dir))

        # Sort by modification date, newest first
        sessions.sort(key=lambda s: s.modified_at, reverse=True)

        return sessions[:limit]

    def _load_sessions_from_index(self, project_dir: Path) -> list[ClaudeSession]:
        """Load sessions from a project's sessions-index.json file."""
        index_file = project_dir / "sessions-index.json"
        if not index_file.exists():
            logger.debug(f"No sessions-index.json found in {project_dir}")
            return []

        try:
            with open(index_file, "r", encoding="utf-8") as f:
                index_data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to read sessions index: {e}")
            return []

        sessions = []
        for entry in index_data.get("entries", []):
            try:
                session = self._parse_session_entry(entry)
                if session:
                    sessions.append(session)
            except Exception as e:
                logger.warning(f"Failed to parse session entry: {e}")

        return sessions

    def _parse_session_entry(self, entry: dict) -> Optional[ClaudeSession]:
        """Parse a session entry from sessions-index.json."""
        session_id = entry.get("sessionId")
        if not session_id:
            return None

        project_path = entry.get("projectPath", "")
        worktree_path = None
        task_id = None

        # Check if this is a worktree session
        if ".worktrees" in project_path or "-worktrees-" in project_path:
            worktree_path = project_path
            task_id = _extract_task_id_from_path(project_path)

        return ClaudeSession(
            session_id=session_id,
            project_path=project_path,
            first_prompt=entry.get("firstPrompt", "")[:200],  # Truncate long prompts
            summary=entry.get("summary"),
            message_count=entry.get("messageCount", 0),
            token_count=0,  # Will be calculated when loading detail
            git_branch=entry.get("gitBranch"),
            worktree_path=worktree_path,
            task_id=task_id,
            created_at=_parse_iso_datetime(entry.get("created", "")),
            modified_at=_parse_iso_datetime(entry.get("modified", "")),
            is_resumable=not entry.get("isSidechain", False)
        )

    def get_session_detail(self, session_id: str, project_path: str) -> Optional[SessionDetail]:
        """
        Get detailed session info including messages.

        Args:
            session_id: The session UUID
            project_path: Path to the project

        Returns:
            SessionDetail with full conversation or None if not found
        """
        # Find the session in the index first
        sessions = self.get_sessions(project_path, include_worktrees=True, limit=1000)
        session = next((s for s in sessions if s.session_id == session_id), None)

        if not session:
            logger.warning(f"Session {session_id} not found in project {project_path}")
            return None

        # Find the session file
        project_dirs = self._find_matching_projects(project_path)
        session_file = None

        for project_dir in project_dirs:
            potential_file = project_dir / f"{session_id}.jsonl"
            if potential_file.exists():
                session_file = potential_file
                break

        if not session_file:
            logger.warning(f"Session file not found for {session_id}")
            return None

        # Parse messages from the jsonl file
        messages, total_tokens = self._parse_session_messages(session_file)

        return SessionDetail(
            session_id=session.session_id,
            project_path=session.project_path,
            first_prompt=session.first_prompt,
            summary=session.summary,
            message_count=len(messages),
            token_count=total_tokens,
            git_branch=session.git_branch,
            worktree_path=session.worktree_path,
            task_id=session.task_id,
            created_at=session.created_at,
            modified_at=session.modified_at,
            is_resumable=session.is_resumable,
            messages=messages
        )

    def _parse_session_messages(self, session_file: Path) -> tuple[list[SessionMessage], int]:
        """
        Parse messages from a session jsonl file.

        Returns:
            Tuple of (messages list, total token count)
        """
        messages: list[SessionMessage] = []
        total_tokens = 0

        try:
            with open(session_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue

                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    entry_type = entry.get("type")
                    if entry_type not in ("user", "assistant"):
                        continue

                    message_data = entry.get("message", {})
                    role = message_data.get("role", entry_type)

                    # Extract content
                    content = ""
                    raw_content = message_data.get("content", "")
                    if isinstance(raw_content, str):
                        content = raw_content
                    elif isinstance(raw_content, list):
                        # Handle content array (tool uses, text blocks)
                        text_parts = []
                        for item in raw_content:
                            if isinstance(item, dict):
                                if item.get("type") == "text":
                                    text_parts.append(item.get("text", ""))
                                elif item.get("type") == "tool_use":
                                    text_parts.append(f"[Tool: {item.get('name', 'unknown')}]")
                                elif item.get("type") == "tool_result":
                                    text_parts.append("[Tool result]")
                        content = "\n".join(text_parts)

                    # Skip empty messages
                    if not content.strip():
                        continue

                    # Extract token count from usage
                    usage = message_data.get("usage", {})
                    tokens = (
                        usage.get("input_tokens", 0) +
                        usage.get("output_tokens", 0) +
                        usage.get("cache_creation_input_tokens", 0) +
                        usage.get("cache_read_input_tokens", 0)
                    )
                    total_tokens += tokens

                    timestamp = _parse_iso_datetime(entry.get("timestamp", ""))

                    messages.append(SessionMessage(
                        role=role,
                        content=content[:10000],  # Truncate very long content
                        timestamp=timestamp,
                        token_count=tokens
                    ))

        except OSError as e:
            logger.error(f"Failed to read session file: {e}")

        return messages, total_tokens

    def delete_session(self, session_id: str, project_path: str) -> bool:
        """
        Delete a session from Claude Code history.

        Args:
            session_id: The session UUID to delete
            project_path: Path to the project

        Returns:
            True if deleted successfully
        """
        project_dirs = self._find_matching_projects(project_path)

        deleted = False
        for project_dir in project_dirs:
            # Delete the session jsonl file
            session_file = project_dir / f"{session_id}.jsonl"
            if session_file.exists():
                try:
                    session_file.unlink()
                    deleted = True
                    logger.info(f"Deleted session file: {session_file}")
                except OSError as e:
                    logger.error(f"Failed to delete session file: {e}")

            # Delete session folder if exists
            session_folder = project_dir / session_id
            if session_folder.exists() and session_folder.is_dir():
                try:
                    import shutil
                    shutil.rmtree(session_folder)
                    logger.info(f"Deleted session folder: {session_folder}")
                except OSError as e:
                    logger.error(f"Failed to delete session folder: {e}")

            # Update sessions-index.json
            index_file = project_dir / "sessions-index.json"
            if index_file.exists():
                try:
                    with open(index_file, "r", encoding="utf-8") as f:
                        index_data = json.load(f)

                    # Filter out the deleted session
                    index_data["entries"] = [
                        e for e in index_data.get("entries", [])
                        if e.get("sessionId") != session_id
                    ]

                    with open(index_file, "w", encoding="utf-8") as f:
                        json.dump(index_data, f, indent=2)

                    logger.info(f"Updated sessions index: {index_file}")
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(f"Failed to update sessions index: {e}")

        return deleted


# Singleton instance
_memory_service: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    """Get the singleton MemoryService instance."""
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
