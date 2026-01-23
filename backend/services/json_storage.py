"""
JSON-based storage service for tasks and configuration.

This module provides atomic file operations with file locking to ensure
data integrity when reading and writing JSON files.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Any
from contextlib import contextmanager

from backend.models import Task, TaskStatus, Phase, PhaseStatus

# Import fcntl only on Unix-like systems
if sys.platform != 'win32':
    import fcntl


class JSONStorage:
    """
    JSON-based storage for tasks and configuration.

    Uses atomic writes (write to temp file then rename) and file locking
    to prevent data corruption.
    """

    def __init__(self, base_path: Path | None = None):
        """
        Initialize JSON storage.

        Args:
            base_path: Base directory for .codeflow storage. Defaults to project root.
        """
        if base_path is None:
            base_path = Path.cwd()

        self.base_path = Path(base_path)
        self.codeflow_dir = self.base_path / ".codeflow"
        self.tasks_file = self.codeflow_dir / "tasks.json"
        self.config_file = self.codeflow_dir / "config.json"
        self.sessions_dir = self.codeflow_dir / "sessions"

        self._ensure_directories()

    def _ensure_directories(self):
        """Create necessary directories if they don't exist."""
        self.codeflow_dir.mkdir(exist_ok=True)
        self.sessions_dir.mkdir(exist_ok=True)

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

    def _atomic_write(self, file_path: Path, data: dict):
        """
        Atomically write data to a JSON file.

        Writes to a temporary file first, then renames it to the target path.
        This ensures the file is never in a partially written state.

        Args:
            file_path: Target file path
            data: Dictionary to serialize to JSON
        """
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with self._file_lock(file_path):
            # Write to temporary file in the same directory
            fd, temp_path = tempfile.mkstemp(
                dir=file_path.parent,
                prefix=f".{file_path.name}.",
                suffix=".tmp"
            )

            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False, default=str)

                # Atomic rename
                temp_path_obj = Path(temp_path)
                temp_path_obj.replace(file_path)
            except Exception:
                # Clean up temp file on error
                try:
                    Path(temp_path).unlink()
                except FileNotFoundError:
                    pass
                raise

    def _read_json(self, file_path: Path) -> dict:
        """
        Read and parse a JSON file with locking.

        Args:
            file_path: Path to JSON file

        Returns:
            Parsed JSON data as dictionary
        """
        if not file_path.exists():
            return {}

        with self._file_lock(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)

    # Task operations

    def load_tasks(self) -> list[Task]:
        """
        Load all tasks from tasks.json.

        Returns:
            List of Task objects
        """
        if not self.tasks_file.exists():
            return []

        data = self._read_json(self.tasks_file)
        tasks = []

        for task_data in data.get("tasks", []):
            # Convert datetime strings back to datetime objects
            if isinstance(task_data.get("created_at"), str):
                task_data["created_at"] = datetime.fromisoformat(task_data["created_at"])
            if isinstance(task_data.get("updated_at"), str):
                task_data["updated_at"] = datetime.fromisoformat(task_data["updated_at"])

            # Convert phase datetime strings
            for phase_key, phase_data in task_data.get("phases", {}).items():
                if isinstance(phase_data.get("started_at"), str):
                    phase_data["started_at"] = datetime.fromisoformat(phase_data["started_at"])
                if isinstance(phase_data.get("completed_at"), str):
                    phase_data["completed_at"] = datetime.fromisoformat(phase_data["completed_at"])

            tasks.append(Task(**task_data))

        return tasks

    def save_tasks(self, tasks: list[Task]):
        """
        Save all tasks to tasks.json atomically.

        Args:
            tasks: List of Task objects to save
        """
        data = {
            "tasks": [task.model_dump(mode="json") for task in tasks],
            "version": "1.0",
            "last_updated": datetime.now().isoformat()
        }

        self._atomic_write(self.tasks_file, data)

    def get_task(self, task_id: str) -> Task | None:
        """
        Get a single task by ID.

        Args:
            task_id: Task identifier

        Returns:
            Task object or None if not found
        """
        tasks = self.load_tasks()
        for task in tasks:
            if task.id == task_id:
                return task
        return None

    def create_task(self, task: Task):
        """
        Create a new task.

        Args:
            task: Task object to create
        """
        tasks = self.load_tasks()
        tasks.append(task)
        self.save_tasks(tasks)

    def update_task(self, task: Task):
        """
        Update an existing task.

        Args:
            task: Task object with updated data
        """
        tasks = self.load_tasks()
        for i, existing_task in enumerate(tasks):
            if existing_task.id == task.id:
                task.updated_at = datetime.now()
                tasks[i] = task
                break
        self.save_tasks(tasks)

    def delete_task(self, task_id: str):
        """
        Delete a task by ID.

        Args:
            task_id: Task identifier
        """
        tasks = self.load_tasks()
        tasks = [t for t in tasks if t.id != task_id]
        self.save_tasks(tasks)

    # Config operations

    def load_config(self) -> dict[str, Any]:
        """
        Load configuration from config.json.

        Returns:
            Configuration dictionary
        """
        if not self.config_file.exists():
            return {}

        return self._read_json(self.config_file)

    def save_config(self, config: dict[str, Any]):
        """
        Save configuration to config.json atomically.

        Args:
            config: Configuration dictionary
        """
        data = {
            **config,
            "last_updated": datetime.now().isoformat()
        }

        self._atomic_write(self.config_file, data)

    def get_config(self, key: str) -> Any | None:
        """
        Get a single configuration value.

        Args:
            key: Configuration key

        Returns:
            Configuration value or None
        """
        config = self.load_config()
        return config.get(key)

    def set_config(self, key: str, value: Any):
        """
        Set a single configuration value.

        Args:
            key: Configuration key
            value: Configuration value
        """
        config = self.load_config()
        config[key] = value
        self.save_config(config)

    # Session logs

    def save_session_log(self, task_id: str, phase: str, log_data: dict):
        """
        Save session log for a task phase.

        Args:
            task_id: Task identifier
            phase: Phase name
            log_data: Log data to save
        """
        session_file = self.sessions_dir / f"{task_id}_{phase}.json"

        data = {
            "task_id": task_id,
            "phase": phase,
            "timestamp": datetime.now().isoformat(),
            **log_data
        }

        self._atomic_write(session_file, data)

    def load_session_log(self, task_id: str, phase: str) -> dict | None:
        """
        Load session log for a task phase.

        Args:
            task_id: Task identifier
            phase: Phase name

        Returns:
            Log data or None if not found
        """
        session_file = self.sessions_dir / f"{task_id}_{phase}.json"

        if not session_file.exists():
            return None

        return self._read_json(session_file)
