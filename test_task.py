import asyncio
import sys
sys.path.insert(0, '.')

from backend.database import get_task
from backend.services.worktree_manager import WorktreeManager
from backend.config import settings
from backend.websocket_manager import manager

async def test_task_execution(task_id: str):
    print(f"[TEST] Starting test for task {task_id}")

    task = await get_task(task_id)
    if not task:
        print(f"[TEST] Task {task_id} not found!")
        return

    print(f"[TEST] Task loaded: {task.title}")
    print(f"[TEST] Status: {task.status}")
    print(f"[TEST] Project path: {settings.project_path}")

    worktree_mgr = WorktreeManager(settings.project_path)

    try:
        branch_name = f"task/{task.id}"
        print(f"[TEST] Creating worktree for branch: {branch_name}")

        worktree_path = worktree_mgr.create(task.id, branch_name)
        print(f"[TEST] Worktree created at: {worktree_path}")

        print(f"[TEST] Sending log via WebSocket...")
        await manager.send_log(task_id, "Test message from script")

        print("[TEST] Cleaning up worktree...")
        worktree_mgr.remove(task.id)

        print("[TEST] Success!")

    except Exception as e:
        print(f"[TEST] ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    task_id = sys.argv[1] if len(sys.argv) > 1 else "001-test-final"
    asyncio.run(test_task_execution(task_id))
