import asyncio
from datetime import datetime
from typing import Callable, Any

from backend.config import settings
from backend.models import TaskStatus


class TaskQueue:
    """
    Manages parallel task execution with a configurable concurrency limit.
    Uses asyncio.Semaphore to limit concurrent tasks and a Queue for pending tasks.
    """

    def __init__(self, max_concurrent: int = None):
        self.max_concurrent = max_concurrent or settings.max_parallel_tasks
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._direct_running: set[str] = set()  # Track directly started tasks
        self._workers_started = False
        self._shutdown = False
        self._executor: Callable[[str, str], Any] = None

    def set_executor(self, executor: Callable[[str, str], Any]):
        """Set the task executor function (execute_task_background)"""
        self._executor = executor

    def register_direct_task(self, task_id: str):
        """Register a directly started task (not via queue)"""
        self._direct_running.add(task_id)
        print(f"[TaskQueue] Direct task registered: {task_id}")

    def unregister_direct_task(self, task_id: str):
        """Unregister a directly started task when it completes"""
        self._direct_running.discard(task_id)
        print(f"[TaskQueue] Direct task unregistered: {task_id}")

    async def start_workers(self):
        """Start the worker loop that processes queued tasks"""
        if self._workers_started:
            return
        self._workers_started = True
        self._shutdown = False
        asyncio.create_task(self._worker_loop())
        print(f"[TaskQueue] Started with max_concurrent={self.max_concurrent}")

    async def _worker_loop(self):
        """Main worker loop that dequeues and executes tasks"""
        print("[TaskQueue] Worker loop started")
        while not self._shutdown:
            try:
                # Wait for a task from the queue (with timeout to check shutdown)
                try:
                    task_id, project_path = await asyncio.wait_for(
                        self._queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                print(f"[TaskQueue] Dequeued task {task_id}, waiting for semaphore...")

                # Acquire semaphore slot
                await self._semaphore.acquire()
                print(f"[TaskQueue] Semaphore acquired for {task_id}")

                # Create and track the task
                task_coro = self._execute_task(task_id, project_path)
                self._running_tasks[task_id] = asyncio.create_task(task_coro)

            except Exception as e:
                print(f"[TaskQueue] Worker error: {e}")
                import traceback
                traceback.print_exc()

    async def _execute_task(self, task_id: str, project_path: str):
        """Execute a single task with semaphore management"""
        from backend.main import storage

        try:
            print(f"[TaskQueue] Starting task {task_id}")

            # Update task status to IN_PROGRESS
            task = storage.get_task(task_id)
            if task:
                task.status = TaskStatus.IN_PROGRESS
                task.updated_at = datetime.now()
                storage.update_task(task)
                print(f"[TaskQueue] Task {task_id} status updated to IN_PROGRESS")

            if self._executor:
                await self._executor(task_id, project_path)
            else:
                print(f"[TaskQueue] No executor set, skipping task {task_id}")

        except Exception as e:
            print(f"[TaskQueue] Task {task_id} failed: {e}")
        finally:
            # Release semaphore and clean up
            self._semaphore.release()
            self._running_tasks.pop(task_id, None)
            print(f"[TaskQueue] Finished task {task_id}")

    async def queue_task(self, task_id: str, project_path: str) -> bool:
        """
        Add a task to the queue. Updates task status to 'queued'.
        Returns True if successfully queued.
        """
        from backend.main import storage

        task = storage.get_task(task_id)
        if not task:
            return False

        # Update status to queued
        task.status = TaskStatus.QUEUED
        task.updated_at = datetime.now()
        storage.update_task(task)

        # Add to queue
        await self._queue.put((task_id, project_path))
        print(f"[TaskQueue] Task {task_id} queued. Queue size: {self._queue.qsize()}")

        return True

    def get_status(self) -> dict:
        """Get current queue status"""
        # Calculate available slots
        # Semaphore._value gives us available permits
        queued_running = self.max_concurrent - self._semaphore._value
        direct_running = len(self._direct_running)
        total_running = queued_running + direct_running
        queued = self._queue.qsize()

        return {
            "running": total_running,
            "queued": queued,
            "max": self.max_concurrent,
            "running_task_ids": list(self._running_tasks.keys()) + list(self._direct_running),
        }

    async def stop_all(self):
        """Stop all running tasks and clear the queue"""
        from backend.main import storage

        self._shutdown = True

        # Cancel all running tasks
        for task_id, task in self._running_tasks.items():
            task.cancel()
            print(f"[TaskQueue] Cancelled task {task_id}")

        # Clear the queue
        while not self._queue.empty():
            try:
                task_id, _ = self._queue.get_nowait()
                # Reset task status to backlog
                task = storage.get_task(task_id)
                if task:
                    task.status = TaskStatus.BACKLOG
                    task.updated_at = datetime.now()
                    storage.update_task(task)
            except asyncio.QueueEmpty:
                break

        self._running_tasks.clear()
        self._workers_started = False
        print("[TaskQueue] Stopped all tasks")

    async def remove_from_queue(self, task_id: str) -> bool:
        """Remove a specific task from the queue (if not yet running)"""
        from backend.main import storage

        if task_id in self._running_tasks:
            return False  # Can't remove running task this way

        # We need to rebuild the queue without the target task
        temp_items = []
        found = False

        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                if item[0] == task_id:
                    found = True
                    # Reset status
                    task = storage.get_task(task_id)
                    if task:
                        task.status = TaskStatus.BACKLOG
                        task.updated_at = datetime.now()
                        storage.update_task(task)
                else:
                    temp_items.append(item)
            except asyncio.QueueEmpty:
                break

        # Put back other items
        for item in temp_items:
            await self._queue.put(item)

        return found


# Global instance
task_queue = TaskQueue()
