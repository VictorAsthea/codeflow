"""
Memory service for storing and retrieving Claude Code session history.

This module provides functionality to track and manage agent sessions,
including conversation history, token usage, and session metadata.
"""

import json
import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

# Import fcntl only on Unix-like systems
if sys.platform != 'win32':
    import fcntl

logger = logging.getLogger(__name__)


class MemoryService:
    """
    Service for managing Claude Code session history.

    Sessions are stored in:
    - .codeflow/memory/sessions.json (index of all sessions)
    - .codeflow/memory/conversations/{taskId}-{timestamp}.json (conversation details)
    """

    def __init__(self, base_path: Path | None = None):
        """
        Initialize the memory service.

        Args:
            base_path: Base directory for .codeflow storage. Defaults to current working directory.
        """
        if base_path is None:
            base_path = Path.cwd()

        self.base_path = Path(base_path)
        self.memory_dir = self.base_path / ".codeflow" / "memory"
        self.sessions_file = self.memory_dir / "sessions.json"
        self.conversations_dir = self.memory_dir / "conversations"

        self._ensure_directories()

    @contextmanager
    def _file_lock(self, file_path: Path):
        """
        Context manager for file locking on Windows and Unix.

        On Windows, uses exclusive file access.
        On Unix-like systems, uses fcntl locking.
        """
        if os.name == 'nt':  # Windows
            # On Windows, we'll use a lock file approach
            lock_file = file_path.with_suffix(file_path.suffix + '.lock')
            lock_fd = None
            try:
                lock_fd = open(lock_file, 'w')
                yield lock_fd
            finally:
                if lock_fd:
                    lock_fd.close()
                    try:
                        lock_file.unlink()
                    except FileNotFoundError:
                        pass
        else:  # Unix-like systems
            lock_file = file_path.with_suffix(file_path.suffix + '.lock')
            lock_fd = None
            try:
                lock_fd = open(lock_file, 'w')
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
                yield lock_fd
            finally:
                if lock_fd:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                    lock_fd.close()
                    try:
                        lock_file.unlink()
                    except FileNotFoundError:
                        pass

    def _ensure_directories(self):
        """Create necessary directories if they don't exist."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.conversations_dir.mkdir(exist_ok=True)

    def _atomic_write(self, file_path: Path, data: dict):
        """
        Atomically write data to a JSON file.

        Writes to a temporary file first, then renames to ensure atomicity.
        """
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with self._file_lock(file_path):
            fd, temp_path = tempfile.mkstemp(
                dir=file_path.parent,
                prefix=f".{file_path.name}.",
                suffix=".tmp"
            )

            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False, default=str)

                temp_path_obj = Path(temp_path)
                temp_path_obj.replace(file_path)
            except Exception:
                try:
                    Path(temp_path).unlink()
                except FileNotFoundError:
                    pass
                raise

    def _read_json(self, file_path: Path) -> dict:
        """Read and parse a JSON file."""
        if not file_path.exists():
            return {}

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to read {file_path}: {e}")
            return {}

    def _read_json_with_lock(self, file_path: Path) -> dict:
        """Read and parse a JSON file with locking."""
        if not file_path.exists():
            return {}

        try:
            with self._file_lock(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to read {file_path}: {e}")
            return {}

    def _load_sessions_index(self) -> list[dict]:
        """Load the sessions index from sessions.json."""
        data = self._read_json(self.sessions_file)
        return data.get("sessions", [])

    def _save_sessions_index(self, sessions: list[dict]):
        """Save the sessions index to sessions.json."""
        data = {
            "sessions": sessions,
            "version": "1.0",
            "last_updated": datetime.now().isoformat()
        }
        self._atomic_write_no_lock(self.sessions_file, data)

    def _atomic_write_no_lock(self, file_path: Path, data: dict):
        """
        Atomically write data to a JSON file without acquiring lock.

        Used when already within a lock context.
        """
        file_path.parent.mkdir(parents=True, exist_ok=True)

        fd, temp_path = tempfile.mkstemp(
            dir=file_path.parent,
            prefix=f".{file_path.name}.",
            suffix=".tmp"
        )

        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)

            temp_path_obj = Path(temp_path)
            temp_path_obj.replace(file_path)
        except Exception:
            try:
                Path(temp_path).unlink()
            except FileNotFoundError:
                pass
            raise

    def list_sessions(self, task_id: str | None = None) -> list[dict]:
        """
        List all sessions, optionally filtered by task ID.

        Args:
            task_id: Optional task ID to filter sessions

        Returns:
            List of session metadata dictionaries
        """
        sessions = self._load_sessions_index()

        if task_id:
            sessions = [s for s in sessions if s.get("task_id") == task_id]

        # Sort by started_at descending (most recent first)
        sessions.sort(key=lambda s: s.get("started_at", ""), reverse=True)

        return sessions

    def get_session(self, session_id: str) -> dict | None:
        """
        Get session details including conversation history.

        Args:
            session_id: The session ID

        Returns:
            Session data with conversation, or None if not found
        """
        sessions = self._load_sessions_index()

        session = next((s for s in sessions if s.get("id") == session_id), None)
        if not session:
            return None

        # Load conversation details
        conversation_file = self.conversations_dir / f"{session_id}.json"
        conversation_data = self._read_json(conversation_file)

        return {
            **session,
            "conversation": conversation_data.get("messages", []),
            "raw_output": conversation_data.get("raw_output"),
            "error": conversation_data.get("error")
        }

    def save_session(self, task_id: str, data: dict) -> dict:
        """
        Save a new session after Claude Code execution.

        Args:
            task_id: The task ID this session belongs to
            data: Session data including:
                - task_title: Title of the task
                - worktree: Worktree/branch name
                - status: Session status (completed, interrupted, failed)
                - messages_count: Number of messages in conversation
                - tokens_used: Total tokens used
                - messages: List of conversation messages (optional)
                - raw_output: Raw Claude output (optional)
                - error: Error message if failed (optional)
                - claude_session_id: Original Claude session ID for --resume (optional)

        Returns:
            The saved session metadata
        """
        timestamp = int(datetime.now().timestamp())
        session_id = f"task-{task_id}-{timestamp}"

        session_meta = {
            "id": session_id,
            "task_id": task_id,
            "task_title": data.get("task_title", ""),
            "worktree": data.get("worktree", ""),
            "started_at": data.get("started_at", datetime.now().isoformat()),
            "ended_at": data.get("ended_at", datetime.now().isoformat()),
            "status": data.get("status", "completed"),
            "messages_count": data.get("messages_count", 0),
            "tokens_used": data.get("tokens_used", 0),
            "claude_session_id": data.get("claude_session_id")
        }

        # Save session metadata to index atomically
        with self._file_lock(self.sessions_file):
            sessions = self._load_sessions_index()
            sessions.append(session_meta)
            self._save_sessions_index(sessions)

        # Save conversation details separately
        conversation_data = {
            "session_id": session_id,
            "task_id": task_id,
            "messages": data.get("messages", []),
            "raw_output": data.get("raw_output"),
            "error": data.get("error"),
            "saved_at": datetime.now().isoformat()
        }
        conversation_file = self.conversations_dir / f"{session_id}.json"
        self._atomic_write(conversation_file, conversation_data)

        logger.info(f"Saved session {session_id} for task {task_id}")
        return session_meta

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session and its conversation data.

        Args:
            session_id: The session ID to delete

        Returns:
            True if deleted, False if not found
        """
        # Delete session from index atomically
        with self._file_lock(self.sessions_file):
            sessions = self._load_sessions_index()
            original_count = len(sessions)

            sessions = [s for s in sessions if s.get("id") != session_id]

            if len(sessions) == original_count:
                return False

            self._save_sessions_index(sessions)

        # Delete conversation file
        conversation_file = self.conversations_dir / f"{session_id}.json"
        if conversation_file.exists():
            conversation_file.unlink()
            logger.info(f"Deleted conversation file for session {session_id}")

        logger.info(f"Deleted session {session_id}")
        return True

    def get_resume_info(self, session_id: str) -> dict | None:
        """
        Get information needed to resume a session with --resume.

        Args:
            session_id: The session ID to resume

        Returns:
            Resume info dict or None if not found
        """
        session = self.get_session(session_id)
        if not session:
            return None

        return {
            "session_id": session_id,
            "task_id": session.get("task_id"),
            "task_title": session.get("task_title"),
            "worktree": session.get("worktree"),
            "claude_session_id": session.get("claude_session_id"),
            "last_status": session.get("status"),
            "can_resume": session.get("claude_session_id") is not None
        }

    def import_from_claude_projects(self, project_path: str | None = None) -> list[dict]:
        """
        Import sessions from ~/.claude/projects/ if available.

        This reads Claude's native session storage and imports relevant sessions.

        Args:
            project_path: Project path to filter sessions (optional)

        Returns:
            List of imported sessions
        """
        claude_projects_dir = Path.home() / ".claude" / "projects"

        if not claude_projects_dir.exists():
            logger.debug("Claude projects directory not found")
            return []

        imported = []

        # Claude stores projects by path hash, look for matching projects
        for project_dir in claude_projects_dir.iterdir():
            if not project_dir.is_dir():
                continue

            sessions_file = project_dir / "sessions.json"
            if not sessions_file.exists():
                continue

            try:
                sessions_data = self._read_json(sessions_file)

                for session in sessions_data.get("sessions", []):
                    # Import if matches project path filter or no filter
                    if project_path is None or session.get("project_path") == project_path:
                        imported_session = self._import_claude_session(session)
                        if imported_session:
                            imported.append(imported_session)
            except Exception as e:
                logger.warning(f"Failed to import from {project_dir}: {e}")

        return imported

    def _import_claude_session(self, claude_session: dict) -> dict | None:
        """Convert and import a Claude session format to our format."""
        try:
            # Extract task ID from prompt or use timestamp
            task_id = claude_session.get("task_id", f"imported-{int(datetime.now().timestamp())}")

            session_data = {
                "task_title": claude_session.get("title", "Imported session"),
                "worktree": claude_session.get("worktree", ""),
                "started_at": claude_session.get("created_at"),
                "ended_at": claude_session.get("updated_at"),
                "status": "imported",
                "messages_count": claude_session.get("message_count", 0),
                "tokens_used": claude_session.get("tokens_used", 0),
                "claude_session_id": claude_session.get("id"),
                "messages": claude_session.get("messages", [])
            }

            return self.save_session(task_id, session_data)
        except Exception as e:
            logger.warning(f"Failed to import Claude session: {e}")
            return None


# Singleton instance
_memory_service: Optional[MemoryService] = None


def get_memory_service(base_path: Path | None = None) -> MemoryService:
    """
    Get the memory service instance.

    Args:
        base_path: Optional base path for storage. If None, uses active project.

    Returns:
        MemoryService instance
    """
    global _memory_service

    if base_path is not None:
        # Return a new instance for specific path
        return MemoryService(base_path=base_path)

    if _memory_service is None:
        # Try to get active project path
        try:
            from backend.services.workspace_service import get_workspace_service
            ws = get_workspace_service()
            state = ws.get_workspace_state()
            project_path = state.get("active_project")
            if project_path:
                _memory_service = MemoryService(base_path=Path(project_path))
            else:
                _memory_service = MemoryService()
        except Exception:
            _memory_service = MemoryService()

    return _memory_service


def reset_memory_service():
    """Reset the singleton instance (useful for testing or project switching)."""
    global _memory_service
    _memory_service = None
