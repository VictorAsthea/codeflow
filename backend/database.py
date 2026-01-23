import json
import aiosqlite
from pathlib import Path
from datetime import datetime
from backend.models import Task, TaskStatus, Phase, PhaseConfig, PhaseStatus
from backend.config import settings


DB_PATH = Path("./data/codeflow.db")


async def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                phases TEXT NOT NULL,
                worktree_path TEXT,
                branch_name TEXT,
                pr_url TEXT,
                pr_number INTEGER,
                pr_merged INTEGER DEFAULT 0,
                pr_merged_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        await db.commit()


async def get_all_tasks() -> list[Task]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks ORDER BY created_at DESC") as cursor:
            rows = await cursor.fetchall()
            return [
                Task(
                    id=row["id"],
                    title=row["title"],
                    description=row["description"],
                    status=TaskStatus(row["status"]),
                    phases={k: Phase(**v) for k, v in json.loads(row["phases"]).items()},
                    worktree_path=row["worktree_path"],
                    branch_name=row["branch_name"],
                    pr_url=row.get("pr_url"),
                    pr_number=row.get("pr_number"),
                    pr_merged=bool(row.get("pr_merged", 0)),
                    pr_merged_at=datetime.fromisoformat(row["pr_merged_at"]) if row.get("pr_merged_at") else None,
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"])
                )
                for row in rows
            ]


async def get_task(task_id: str) -> Task | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Task(
                id=row["id"],
                title=row["title"],
                description=row["description"],
                status=TaskStatus(row["status"]),
                phases={k: Phase(**v) for k, v in json.loads(row["phases"]).items()},
                worktree_path=row["worktree_path"],
                branch_name=row["branch_name"],
                pr_url=row.get("pr_url"),
                pr_number=row.get("pr_number"),
                pr_merged=bool(row.get("pr_merged", 0)),
                pr_merged_at=datetime.fromisoformat(row["pr_merged_at"]) if row.get("pr_merged_at") else None,
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"])
            )


async def create_task(task: Task):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO tasks (id, title, description, status, phases, worktree_path, branch_name, pr_url, pr_number, pr_merged, pr_merged_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.id,
                task.title,
                task.description,
                task.status.value,
                json.dumps({k: v.model_dump(mode="json") for k, v in task.phases.items()}),
                task.worktree_path,
                task.branch_name,
                task.pr_url,
                task.pr_number,
                int(task.pr_merged),
                task.pr_merged_at.isoformat() if task.pr_merged_at else None,
                task.created_at.isoformat(),
                task.updated_at.isoformat()
            )
        )
        await db.commit()


async def update_task(task: Task):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE tasks
            SET title = ?, description = ?, status = ?, phases = ?,
                worktree_path = ?, branch_name = ?, pr_url = ?, pr_number = ?,
                pr_merged = ?, pr_merged_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                task.title,
                task.description,
                task.status.value,
                json.dumps({k: v.model_dump(mode="json") for k, v in task.phases.items()}),
                task.worktree_path,
                task.branch_name,
                task.pr_url,
                task.pr_number,
                int(task.pr_merged),
                task.pr_merged_at.isoformat() if task.pr_merged_at else None,
                datetime.now().isoformat(),
                task.id
            )
        )
        await db.commit()


async def delete_task(task_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await db.commit()


async def get_config(key: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM config WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def set_config(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, value)
        )
        await db.commit()
