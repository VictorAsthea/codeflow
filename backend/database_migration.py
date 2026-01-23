"""
Database migration script to add PR monitoring fields to existing tasks table.
Run this script once to update the database schema for PR auto-stop feature.
"""

import asyncio
import aiosqlite
from pathlib import Path

DB_PATH = Path("./data/codeflow.db")


async def migrate_database():
    """Add PR monitoring fields to tasks table"""
    if not DB_PATH.exists():
        print("❌ Database not found. No migration needed.")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("PRAGMA table_info(tasks)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]

        migrations_needed = []

        if "pr_url" not in column_names:
            migrations_needed.append("ALTER TABLE tasks ADD COLUMN pr_url TEXT")

        if "pr_number" not in column_names:
            migrations_needed.append("ALTER TABLE tasks ADD COLUMN pr_number INTEGER")

        if "pr_merged" not in column_names:
            migrations_needed.append("ALTER TABLE tasks ADD COLUMN pr_merged INTEGER DEFAULT 0")

        if "pr_merged_at" not in column_names:
            migrations_needed.append("ALTER TABLE tasks ADD COLUMN pr_merged_at TEXT")

        if not migrations_needed:
            print("✅ Database schema is already up to date. No migration needed.")
            return

        print(f"🔧 Running {len(migrations_needed)} migration(s)...")

        for migration in migrations_needed:
            print(f"   - {migration}")
            await db.execute(migration)

        await db.commit()
        print("✅ Database migration completed successfully!")


if __name__ == "__main__":
    asyncio.run(migrate_database())
