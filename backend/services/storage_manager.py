"""
Storage manager for multi-project support.

Provides project-specific JSONStorage instances based on the active workspace project.
"""

from pathlib import Path
from typing import Dict, Optional

from backend.services.json_storage import JSONStorage
from backend.services.workspace_service import get_workspace_service


class StorageManager:
    """Manages JSONStorage instances per project."""

    def __init__(self):
        self._storages: Dict[str, JSONStorage] = {}

    def get_storage(self, project_path: Optional[str] = None) -> JSONStorage:
        """
        Get JSONStorage for a specific project or the active project.

        Args:
            project_path: Optional project path. If None, uses active project.

        Returns:
            JSONStorage instance for the project
        """
        if project_path is None:
            project_path = self._get_active_project_path()

        if project_path is None:
            # Fallback to current directory
            project_path = str(Path.cwd())

        # Normalize path
        project_path = str(Path(project_path).resolve())

        # Create storage if not cached
        if project_path not in self._storages:
            self._storages[project_path] = JSONStorage(base_path=Path(project_path))

        return self._storages[project_path]

    def _get_active_project_path(self) -> Optional[str]:
        """Get the active project path from workspace service."""
        try:
            ws = get_workspace_service()
            state = ws.get_workspace_state()
            return state.get("active_project")
        except Exception:
            return None

    def clear_cache(self):
        """Clear all cached storage instances."""
        self._storages.clear()


# Singleton instance
_storage_manager: Optional[StorageManager] = None


def get_storage_manager() -> StorageManager:
    """Get the global storage manager instance."""
    global _storage_manager
    if _storage_manager is None:
        _storage_manager = StorageManager()
    return _storage_manager


def get_project_storage(project_path: Optional[str] = None) -> JSONStorage:
    """
    Convenience function to get storage for a project.

    Args:
        project_path: Optional project path. If None, uses active project.

    Returns:
        JSONStorage instance for the project
    """
    return get_storage_manager().get_storage(project_path)
