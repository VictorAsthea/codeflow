"""
Automatic migration from SQLite to JSON storage.

This module handles the one-time migration of tasks and configuration
from the SQLite database to JSON files.
"""

import shutil
import logging
from pathlib import Path
from typing import Callable, Any

logger = logging.getLogger(__name__)


class StorageMigration:
    """Handles migration from SQLite to JSON storage."""

    def __init__(self, db_path: Path, json_storage):
        """
        Initialize migration handler.

        Args:
            db_path: Path to SQLite database file
            json_storage: JSONStorage instance
        """
        self.db_path = db_path
        self.json_storage = json_storage
        self.backup_path = db_path.with_suffix('.db.bak')

    async def needs_migration(self) -> bool:
        """
        Check if migration is needed.

        Returns:
            True if SQLite database exists and JSON storage is empty
        """
        has_sqlite = self.db_path.exists()
        has_json = self.json_storage.tasks_file.exists()

        return has_sqlite and not has_json

    async def migrate(self) -> dict[str, Any]:
        """
        Perform the migration from SQLite to JSON.

        Returns:
            Migration statistics
        """
        if not await self.needs_migration():
            logger.info("No migration needed")
            return {
                "migrated": False,
                "reason": "Migration not needed"
            }

        logger.info("Starting migration from SQLite to JSON storage")

        # Import SQLite functions (only when needed)
        from backend.database import get_all_tasks, get_config

        try:
            # Migrate tasks
            tasks = await get_all_tasks()
            self.json_storage.save_tasks(tasks)

            task_count = len(tasks)
            logger.info(f"Migrated {task_count} tasks to JSON storage")

            # Migrate config
            config_keys = [
                "default_model",
                "default_intensity",
                "project_path",
                "auto_review",
                "auto_resume_enabled",
                "auto_resume_max_retries",
                "auto_resume_delay_seconds",
                "max_parallel_tasks"
            ]

            config = {}
            for key in config_keys:
                value = await get_config(key)
                if value is not None:
                    config[key] = value

            if config:
                self.json_storage.save_config(config)
                logger.info(f"Migrated {len(config)} configuration values")

            # Backup SQLite database
            self._backup_sqlite()

            logger.info("Migration completed successfully")

            return {
                "migrated": True,
                "tasks_count": task_count,
                "config_keys": len(config),
                "backup_path": str(self.backup_path)
            }

        except Exception as e:
            logger.error(f"Migration failed: {e}", exc_info=True)
            # Clean up partial migration
            if self.json_storage.tasks_file.exists():
                self.json_storage.tasks_file.unlink()
            if self.json_storage.config_file.exists():
                self.json_storage.config_file.unlink()

            raise RuntimeError(f"Migration failed: {e}") from e

    def _backup_sqlite(self):
        """Create backup of SQLite database."""
        if self.db_path.exists():
            shutil.copy2(self.db_path, self.backup_path)
            logger.info(f"SQLite database backed up to {self.backup_path}")


async def run_migration_if_needed(db_path: Path, json_storage) -> dict[str, Any]:
    """
    Run migration if needed.

    Args:
        db_path: Path to SQLite database
        json_storage: JSONStorage instance

    Returns:
        Migration result dictionary
    """
    migration = StorageMigration(db_path, json_storage)

    if await migration.needs_migration():
        logger.info("Migration required - starting automatic migration")
        result = await migration.migrate()
        logger.info(f"Migration completed: {result}")
        return result

    return {"migrated": False, "reason": "No migration needed"}
