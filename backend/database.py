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
                review_issues TEXT,
                review_cycles INTEGER DEFAULT 0,
                review_status TEXT,
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
            return [_row_to_task(row) for row in rows]


def _row_to_task(row) -> Task:
    """Convert a database row to a Task object."""
    # Get available columns to handle older database schemas
    cols = set(row.keys())

    def get_col(name, default=None):
        return row[name] if name in cols else default

    return Task(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=TaskStatus(row["status"]),
        phases={k: Phase(**v) for k, v in json.loads(row["phases"]).items()},
        worktree_path=get_col("worktree_path"),
        branch_name=get_col("branch_name"),
        pr_url=get_col("pr_url"),
        pr_number=get_col("pr_number"),
        pr_merged=bool(get_col("pr_merged", 0) or 0),
        pr_merged_at=datetime.fromisoformat(row["pr_merged_at"]) if get_col("pr_merged_at") else None,
        review_issues=json.loads(row["review_issues"]) if get_col("review_issues") else None,
        review_cycles=get_col("review_cycles", 0) or 0,
        review_status=get_col("review_status"),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"])
    )


async def get_task(task_id: str) -> Task | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return _row_to_task(row)


async def create_task(task: Task):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO tasks (id, title, description, status, phases, worktree_path, branch_name,
                pr_url, pr_number, pr_merged, pr_merged_at,
                review_issues, review_cycles, review_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(task.review_issues) if task.review_issues else None,
                task.review_cycles,
                task.review_status,
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
                worktree_path = ?, branch_name = ?,
                pr_url = ?, pr_number = ?, pr_merged = ?, pr_merged_at = ?,
                review_issues = ?, review_cycles = ?, review_status = ?, updated_at = ?
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
                json.dumps(task.review_issues) if task.review_issues else None,
                task.review_cycles,
                task.review_status,
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
