import asyncio
import heapq
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Any, Optional

from backend.config import settings
from backend.models import TaskStatus

logger = logging.getLogger(__name__)


def get_conflict_detector():
    """Get conflict detector instance (lazy import to avoid circular dependency)"""
    from backend.services.conflict_detector import conflict_detector
    return conflict_detector


def get_parallel_manager():
    """Get parallel manager instance (lazy import to avoid circular dependency)"""
    from backend.websocket_manager import parallel_manager
    return parallel_manager


class TaskPriority(str, Enum):
    """Priority levels for task execution"""
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


# Priority values for heap ordering (lower = higher priority)
PRIORITY_VALUES = {
    TaskPriority.HIGH: 0,
    TaskPriority.NORMAL: 1,
    TaskPriority.LOW: 2,
}


@dataclass(order=True)
class PriorityItem:
    """A priority queue item that orders by priority then by timestamp"""
    priority_value: int
    timestamp: float = field(compare=True)
    task_id: str = field(compare=False)
    project_path: str = field(compare=False)
    priority: TaskPriority = field(compare=False)


class QueuedTaskInfo:
    """Information about a queued task"""
    def __init__(
        self,
        task_id: str,
        project_path: str,
        priority: TaskPriority,
        queued_at: datetime,
        position: int = 0,
        estimated_duration: float = None
    ):
        self.task_id = task_id
        self.project_path = project_path
        self.priority = priority
        self.queued_at = queued_at
        self.position = position
        self.estimated_duration = estimated_duration

    def to_dict(self) -> dict:
        result = {
            "task_id": self.task_id,
            "project_path": self.project_path,
            "priority": self.priority.value,
            "queued_at": self.queued_at.isoformat(),
            "position": self.position
        }
        if self.estimated_duration:
            result["estimated_duration"] = self.estimated_duration
        return result


class RunningTaskInfo:
    """Information about a running task"""
    def __init__(
        self,
        task_id: str,
        project_path: str,
        started_at: datetime,
        priority: TaskPriority = TaskPriority.NORMAL,
        estimated_duration: float = None
    ):
        self.task_id = task_id
        self.project_path = project_path
        self.started_at = started_at
        self.priority = priority
        self.estimated_duration = estimated_duration

    def to_dict(self) -> dict:
        elapsed = (datetime.now() - self.started_at).total_seconds()
        result = {
            "task_id": self.task_id,
            "project_path": self.project_path,
            "priority": self.priority.value,
            "started_at": self.started_at.isoformat(),
            "elapsed_seconds": elapsed
        }
        if self.estimated_duration:
            result["estimated_duration"] = self.estimated_duration
            result["estimated_remaining"] = max(0, self.estimated_duration - elapsed)
            result["estimated_completion"] = (
                self.started_at + timedelta(seconds=self.estimated_duration)
            ).isoformat()
        return result


class TaskQueue:
    """
    Manages parallel task execution with a configurable concurrency limit.
    Uses asyncio.Semaphore to limit concurrent tasks and a priority heap for pending tasks.
    Supports pause/resume functionality and batch operations.
    """

    def __init__(self, max_concurrent: int = None):
        self.max_concurrent = max_concurrent or settings.max_parallel_tasks
        self._semaphore = None  # Created in start_workers
        self._priority_heap: list[PriorityItem] = []
        self._heap_lock = asyncio.Lock() if asyncio.get_event_loop_policy() else None
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._running_task_info: dict[str, RunningTaskInfo] = {}
        self._queued_task_info: dict[str, QueuedTaskInfo] = {}
        self._direct_running: set[str] = set()  # Track directly started tasks
        self._workers_started = False
        self._shutdown = False
        self._paused = False
        self._pause_event = None  # Created in start_workers
        self._executor: Callable[[str, str], Any] = None
        self._sequence_counter = 0  # For FIFO ordering within same priority

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

        # Create synchronization primitives in the event loop context
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._heap_lock = asyncio.Lock()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Not paused initially

        self._workers_started = True
        self._shutdown = False
        asyncio.create_task(self._worker_loop())
        print(f"[TaskQueue] Started with max_concurrent={self.max_concurrent}")

    async def _worker_loop(self):
        """Main worker loop that dequeues and executes tasks"""
        print("[TaskQueue] Worker loop started")
        while not self._shutdown:
            try:
                # Wait if paused
                await self._pause_event.wait()

                # Check if there are tasks in the heap
                async with self._heap_lock:
                    if not self._priority_heap:
                        await asyncio.sleep(0.5)
                        continue

                    # Pop the highest priority task
                    item = heapq.heappop(self._priority_heap)
                    task_id = item.task_id
                    project_path = item.project_path
                    priority = item.priority

                    # Remove from queued info
                    self._queued_task_info.pop(task_id, None)

                # Get estimated duration before losing queued info
                estimated_duration = self._queued_task_info.get(task_id)
                estimated_duration = estimated_duration.estimated_duration if estimated_duration else self.estimate_task_duration(task_id)

                print(f"[TaskQueue] Dequeued task {task_id} (priority: {priority.value}), waiting for semaphore...")

                # Acquire semaphore slot
                await self._semaphore.acquire()
                print(f"[TaskQueue] Semaphore acquired for {task_id}")

                # Track running task info with estimated duration
                self._running_task_info[task_id] = RunningTaskInfo(
                    task_id=task_id,
                    project_path=project_path,
                    started_at=datetime.now(),
                    priority=priority,
                    estimated_duration=estimated_duration
                )

                # Create and track the task
                task_coro = self._execute_task(task_id, project_path)
                self._running_tasks[task_id] = asyncio.create_task(task_coro)

                # Notify parallel manager of queue change
                asyncio.create_task(self._notify_queue_change())

            except Exception as e:
                print(f"[TaskQueue] Worker error: {e}")
                import traceback
                traceback.print_exc()

    async def _execute_task(self, task_id: str, project_path: str):
        """Execute a single task with semaphore management"""
        from backend.main import storage

        execution_start = datetime.now()

        try:
            print(f"[TaskQueue] Starting task {task_id}")

            # Update task status to IN_PROGRESS and record start time
            task = storage.get_task(task_id)
            if task:
                task.status = TaskStatus.IN_PROGRESS
                task.execution_started_at = execution_start
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
            # Record execution completion and duration
            execution_end = datetime.now()
            task = storage.get_task(task_id)
            if task:
                task.execution_completed_at = execution_end
                task.execution_duration_seconds = (execution_end - execution_start).total_seconds()
                task.updated_at = execution_end
                storage.update_task(task)
                print(f"[TaskQueue] Task {task_id} execution duration: {task.execution_duration_seconds:.1f}s")

            # Release semaphore and clean up
            self._semaphore.release()
            self._running_tasks.pop(task_id, None)
            self._running_task_info.pop(task_id, None)
            print(f"[TaskQueue] Finished task {task_id}")

            # Notify parallel manager of queue change
            asyncio.create_task(self._notify_queue_change())

    def check_conflicts_for_task(self, task_id: str) -> list[dict]:
        """
        Check if a task has potential conflicts with running or queued tasks.

        Args:
            task_id: The task to check

        Returns:
            List of conflict dictionaries with details
        """
        from backend.main import storage

        task = storage.get_task(task_id)
        if not task:
            return []

        detector = get_conflict_detector()
        conflicts = []

        # Get all running and queued task IDs
        active_task_ids = (
            list(self._running_tasks.keys()) +
            list(self._direct_running) +
            list(self._queued_task_info.keys())
        )

        # Get task objects for conflict checking
        active_tasks = []
        for tid in active_task_ids:
            if tid != task_id:
                other_task = storage.get_task(tid)
                if other_task:
                    active_tasks.append(other_task)

        # Check for conflicts
        task_conflicts = detector.get_task_conflicts(task, active_tasks)
        for conflict in task_conflicts:
            conflicts.append(conflict.to_dict())

        return conflicts

    async def queue_task(
        self,
        task_id: str,
        project_path: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        check_conflicts: bool = True
    ) -> dict:
        """
        Add a task to the queue with the specified priority.
        Updates task status to 'queued'.

        Args:
            task_id: The task ID to queue
            project_path: Project path
            priority: Task priority
            check_conflicts: Whether to check for conflicts (default True)

        Returns:
            Dict with 'success', optional 'conflicts', and 'queued' status
        """
        from backend.main import storage

        # Ensure workers are started
        if not self._workers_started:
            print("[TaskQueue] ERROR: Workers not started. Call start_workers first.")
            return {"success": False, "error": "Workers not started"}

        task = storage.get_task(task_id)
        if not task:
            return {"success": False, "error": "Task not found"}

        # Check for conflicts if requested
        conflicts = []
        if check_conflicts:
            conflicts = self.check_conflicts_for_task(task_id)
            if conflicts:
                # Log conflict warnings
                high_severity = [c for c in conflicts if c.get("severity") == "high"]
                if high_severity:
                    print(f"[TaskQueue] WARNING: Task {task_id} has {len(high_severity)} high-severity conflicts")

        # Update status to queued
        task.status = TaskStatus.QUEUED
        task.updated_at = datetime.now()
        storage.update_task(task)

        # Estimate duration for scheduling
        estimated_duration = self.estimate_task_duration(task_id)

        # Add to priority heap
        now = datetime.now()
        self._sequence_counter += 1
        item = PriorityItem(
            priority_value=PRIORITY_VALUES[priority],
            timestamp=now.timestamp() + (self._sequence_counter * 0.0001),  # Ensure FIFO within priority
            task_id=task_id,
            project_path=project_path,
            priority=priority
        )

        async with self._heap_lock:
            heapq.heappush(self._priority_heap, item)
            position = len(self._priority_heap)

            # Track queued task info with estimated duration
            self._queued_task_info[task_id] = QueuedTaskInfo(
                task_id=task_id,
                project_path=project_path,
                priority=priority,
                queued_at=now,
                position=position,
                estimated_duration=estimated_duration
            )

        print(f"[TaskQueue] Task {task_id} queued with priority {priority.value}. Queue size: {len(self._priority_heap)}")

        # Notify parallel manager of queue change
        asyncio.create_task(self._notify_queue_change())

        result = {"success": True, "queued": True}
        if conflicts:
            result["conflicts"] = conflicts
            result["has_conflicts"] = True

        return result

    async def _notify_queue_change(self):
        """Notify parallel manager of queue status change"""
        try:
            pm = get_parallel_manager()
            await pm.notify_queue_changed(self.get_detailed_status())
        except Exception as e:
            logger.warning(f"Failed to notify parallel manager of queue change: {e}")

    async def batch_queue_tasks(
        self,
        tasks: list[dict],
        check_conflicts: bool = True
    ) -> dict:
        """
        Add multiple tasks to the queue at once.

        Args:
            tasks: List of dicts with 'task_id', 'project_path', and optional 'priority'
            check_conflicts: Whether to check for conflicts (default True)

        Returns:
            Dict with 'queued' (list of successfully queued task IDs),
            'failed' (list of dicts with 'task_id' and 'error'),
            and 'conflicts' (list of detected conflicts)
        """
        queued = []
        failed = []
        all_conflicts = []

        for task_data in tasks:
            task_id = task_data.get("task_id")
            project_path = task_data.get("project_path")
            priority_str = task_data.get("priority", "normal")

            if not task_id or not project_path:
                failed.append({
                    "task_id": task_id,
                    "error": "Missing task_id or project_path"
                })
                continue

            try:
                priority = TaskPriority(priority_str)
            except ValueError:
                priority = TaskPriority.NORMAL

            result = await self.queue_task(task_id, project_path, priority, check_conflicts)
            if result.get("success"):
                queued.append(task_id)
                if result.get("conflicts"):
                    all_conflicts.extend(result["conflicts"])
            else:
                failed.append({
                    "task_id": task_id,
                    "error": result.get("error", "Failed to queue task")
                })

        response = {
            "queued": queued,
            "failed": failed,
            "queue_status": self.get_status()
        }

        if all_conflicts:
            response["conflicts"] = all_conflicts
            response["has_conflicts"] = True

        return response

    async def reorder_queue(self, task_order: list[str]) -> bool:
        """
        Reorder queued tasks according to the provided order.
        Tasks not in the list will be appended at the end.

        Args:
            task_order: List of task IDs in desired execution order

        Returns:
            True if reordering was successful
        """
        async with self._heap_lock:
            # Extract all items from heap
            items_by_id = {}
            while self._priority_heap:
                item = heapq.heappop(self._priority_heap)
                items_by_id[item.task_id] = item

            if not items_by_id:
                return True  # Nothing to reorder

            # Rebuild heap with new order
            # Tasks in task_order get sequential timestamps (preserving their position)
            # Tasks not in task_order keep their original timestamps
            base_time = datetime.now().timestamp()
            new_heap = []

            # First, add tasks in the specified order with high priority timestamps
            for i, task_id in enumerate(task_order):
                if task_id in items_by_id:
                    item = items_by_id.pop(task_id)
                    # Create new item with updated timestamp for ordering
                    new_item = PriorityItem(
                        priority_value=item.priority_value,
                        timestamp=base_time + (i * 0.0001),
                        task_id=item.task_id,
                        project_path=item.project_path,
                        priority=item.priority
                    )
                    heapq.heappush(new_heap, new_item)

            # Add remaining tasks (not in task_order) at the end
            for task_id, item in items_by_id.items():
                new_item = PriorityItem(
                    priority_value=item.priority_value,
                    timestamp=base_time + 1000 + item.timestamp,  # Put at end
                    task_id=item.task_id,
                    project_path=item.project_path,
                    priority=item.priority
                )
                heapq.heappush(new_heap, new_item)

            self._priority_heap = new_heap

            # Update positions in queued_task_info
            for i, task_id in enumerate(task_order):
                if task_id in self._queued_task_info:
                    self._queued_task_info[task_id].position = i + 1

        print(f"[TaskQueue] Queue reordered. New order: {task_order}")
        return True

    def get_status(self) -> dict:
        """Get current queue status"""
        # Handle case where workers not yet started
        if not self._semaphore:
            return {
                "running": len(self._direct_running),
                "queued": 0,
                "max": self.max_concurrent,
                "running_task_ids": list(self._direct_running),
                "paused": self._paused
            }

        # Calculate available slots
        queued_running = self.max_concurrent - self._semaphore._value
        direct_running = len(self._direct_running)
        total_running = queued_running + direct_running
        queued = len(self._priority_heap)

        return {
            "running": total_running,
            "queued": queued,
            "max": self.max_concurrent,
            "running_task_ids": list(self._running_tasks.keys()) + list(self._direct_running),
            "paused": self._paused
        }

    def get_detailed_status(self) -> dict:
        """
        Get detailed queue status with per-task progress info.

        Returns:
            Dict containing:
            - running_tasks: List of running task info
            - queued_tasks: List of queued task info
            - queue_stats: Summary statistics
            - paused: Whether queue is paused
        """
        from backend.main import storage

        # Get running tasks info
        running_tasks = []
        for task_id, info in self._running_task_info.items():
            task = storage.get_task(task_id)
            task_info = info.to_dict()
            if task:
                task_info.update({
                    "title": task.title,
                    "current_phase": task.current_phase,
                    "current_subtask_id": task.current_subtask_id,
                    "status": task.status.value
                })
            running_tasks.append(task_info)

        # Also include directly started tasks
        for task_id in self._direct_running:
            if task_id not in self._running_task_info:
                task = storage.get_task(task_id)
                task_info = {
                    "task_id": task_id,
                    "priority": "normal",
                    "started_at": None,
                    "elapsed_seconds": 0,
                    "direct_start": True
                }
                if task:
                    task_info.update({
                        "title": task.title,
                        "current_phase": task.current_phase,
                        "current_subtask_id": task.current_subtask_id,
                        "status": task.status.value
                    })
                running_tasks.append(task_info)

        # Get queued tasks info (sorted by position)
        queued_tasks = []
        sorted_queue = sorted(
            self._queued_task_info.values(),
            key=lambda x: (PRIORITY_VALUES[x.priority], x.queued_at)
        )
        for i, info in enumerate(sorted_queue):
            info.position = i + 1
            task = storage.get_task(info.task_id)
            task_info = info.to_dict()
            if task:
                task_info.update({
                    "title": task.title
                })
            queued_tasks.append(task_info)

        # Calculate stats
        by_priority = {"high": 0, "normal": 0, "low": 0}
        for info in self._queued_task_info.values():
            by_priority[info.priority.value] += 1

        return {
            "running_tasks": running_tasks,
            "queued_tasks": queued_tasks,
            "queue_stats": {
                "running_count": len(running_tasks),
                "queued_count": len(queued_tasks),
                "max_concurrent": self.max_concurrent,
                "available_slots": self._semaphore._value if self._semaphore else self.max_concurrent,
                "by_priority": by_priority
            },
            "paused": self._paused
        }

    async def pause(self) -> bool:
        """
        Pause the queue. Running tasks will complete, but no new tasks will start.

        Returns:
            True if queue was paused, False if already paused
        """
        if self._paused:
            return False

        self._paused = True
        if self._pause_event:
            self._pause_event.clear()
        print("[TaskQueue] Queue paused")
        return True

    async def resume(self) -> bool:
        """
        Resume the queue after pause.

        Returns:
            True if queue was resumed, False if not paused
        """
        if not self._paused:
            return False

        self._paused = False
        if self._pause_event:
            self._pause_event.set()
        print("[TaskQueue] Queue resumed")
        return True

    def is_paused(self) -> bool:
        """Check if queue is paused"""
        return self._paused

    async def stop_all(self):
        """Stop all running tasks and clear the queue"""
        from backend.main import storage

        self._shutdown = True

        # Cancel all running tasks
        for task_id, task in self._running_tasks.items():
            task.cancel()
            print(f"[TaskQueue] Cancelled task {task_id}")

        # Clear the priority heap
        async with self._heap_lock:
            while self._priority_heap:
                item = heapq.heappop(self._priority_heap)
                task_id = item.task_id
                # Reset task status to backlog
                task = storage.get_task(task_id)
                if task:
                    task.status = TaskStatus.BACKLOG
                    task.updated_at = datetime.now()
                    storage.update_task(task)

        self._running_tasks.clear()
        self._running_task_info.clear()
        self._queued_task_info.clear()
        self._workers_started = False
        print("[TaskQueue] Stopped all tasks")

    async def remove_from_queue(self, task_id: str) -> bool:
        """Remove a specific task from the queue (if not yet running)"""
        from backend.main import storage

        if task_id in self._running_tasks:
            return False  # Can't remove running task this way

        async with self._heap_lock:
            # Find and remove the task from the heap
            found = False
            new_heap = []
            while self._priority_heap:
                item = heapq.heappop(self._priority_heap)
                if item.task_id == task_id:
                    found = True
                    # Reset status
                    task = storage.get_task(task_id)
                    if task:
                        task.status = TaskStatus.BACKLOG
                        task.updated_at = datetime.now()
                        storage.update_task(task)
                    # Remove from queued info
                    self._queued_task_info.pop(task_id, None)
                else:
                    heapq.heappush(new_heap, item)

            self._priority_heap = new_heap

        return found

    async def update_task_priority(
        self,
        task_id: str,
        new_priority: TaskPriority
    ) -> bool:
        """
        Update the priority of a queued task.

        Args:
            task_id: The task to update
            new_priority: The new priority level

        Returns:
            True if priority was updated, False if task not found in queue
        """
        async with self._heap_lock:
            # Find and update the task in the heap
            found = False
            new_heap = []
            while self._priority_heap:
                item = heapq.heappop(self._priority_heap)
                if item.task_id == task_id:
                    found = True
                    # Create new item with updated priority
                    new_item = PriorityItem(
                        priority_value=PRIORITY_VALUES[new_priority],
                        timestamp=item.timestamp,
                        task_id=item.task_id,
                        project_path=item.project_path,
                        priority=new_priority
                    )
                    heapq.heappush(new_heap, new_item)
                    # Update queued info
                    if task_id in self._queued_task_info:
                        self._queued_task_info[task_id].priority = new_priority
                else:
                    heapq.heappush(new_heap, item)

            self._priority_heap = new_heap

        if found:
            print(f"[TaskQueue] Task {task_id} priority updated to {new_priority.value}")
        return found

    def estimate_task_duration(self, task_id: str) -> float:
        """
        Estimate task execution duration based on subtask count and historical data.

        The estimation uses:
        1. Historical average duration from completed tasks with similar subtask counts
        2. Base duration per subtask (with a minimum baseline)
        3. Complexity adjustment based on agent profile

        Returns:
            Estimated duration in seconds
        """
        from backend.main import storage

        task = storage.get_task(task_id)
        if not task:
            return 600.0  # Default 10 minutes

        # Base duration per subtask (empirical: ~3 minutes per subtask average)
        BASE_DURATION_PER_SUBTASK = 180.0
        # Minimum duration for any task
        MIN_DURATION = 300.0  # 5 minutes
        # Complexity multipliers based on agent profile
        PROFILE_MULTIPLIERS = {
            "quick": 0.6,
            "balanced": 1.0,
            "thorough": 1.5
        }

        subtask_count = len(task.subtasks) if task.subtasks else 3  # Assume 3 if not yet planned
        profile_multiplier = PROFILE_MULTIPLIERS.get(task.agent_profile.value, 1.0)

        # Calculate from historical data
        all_tasks = storage.load_tasks()
        completed_with_duration = [
            t for t in all_tasks
            if t.execution_duration_seconds and t.execution_duration_seconds > 0
        ]

        if completed_with_duration:
            # Group by similar subtask counts (within +/- 2)
            similar_tasks = [
                t for t in completed_with_duration
                if abs(len(t.subtasks) - subtask_count) <= 2
            ]

            if similar_tasks:
                # Use average duration of similar tasks
                avg_duration = sum(t.execution_duration_seconds for t in similar_tasks) / len(similar_tasks)
                estimated = avg_duration * profile_multiplier
                return max(MIN_DURATION, estimated)

            # Fallback: calculate average duration per subtask from all completed tasks
            total_subtasks = sum(len(t.subtasks) if t.subtasks else 1 for t in completed_with_duration)
            total_duration = sum(t.execution_duration_seconds for t in completed_with_duration)
            if total_subtasks > 0:
                avg_per_subtask = total_duration / total_subtasks
                estimated = subtask_count * avg_per_subtask * profile_multiplier
                return max(MIN_DURATION, estimated)

        # No historical data: use base estimation
        estimated = subtask_count * BASE_DURATION_PER_SUBTASK * profile_multiplier
        return max(MIN_DURATION, estimated)

    async def optimize_queue_order(self) -> list[str]:
        """
        Optimize queue order to maximize throughput using shortest job first heuristic.

        This considers:
        1. Task priority (high priority tasks always come first within their group)
        2. Estimated duration (shorter tasks first to reduce average wait time)
        3. Time in queue (prevent starvation of long tasks)

        Returns:
            Optimized list of task IDs in execution order
        """
        from backend.main import storage

        async with self._heap_lock:
            if not self._priority_heap:
                return []

            # Extract all tasks from queue with their metadata
            tasks_data = []
            for item in self._priority_heap:
                task = storage.get_task(item.task_id)
                if task:
                    estimated_duration = self.estimate_task_duration(item.task_id)
                    time_in_queue = (datetime.now() - datetime.fromtimestamp(item.timestamp)).total_seconds()
                    tasks_data.append({
                        "task_id": item.task_id,
                        "priority": item.priority,
                        "priority_value": item.priority_value,
                        "estimated_duration": estimated_duration,
                        "time_in_queue": time_in_queue,
                        "original_timestamp": item.timestamp
                    })

            if not tasks_data:
                return []

            # Sort by: priority first, then by weighted score
            # Score = estimated_duration - (time_in_queue * 0.1)
            # This prefers shorter tasks but prevents starvation of long-waiting tasks
            def sort_key(t):
                # Starvation prevention: reduce effective duration by 10% of wait time
                effective_duration = t["estimated_duration"] - (t["time_in_queue"] * 0.1)
                return (t["priority_value"], effective_duration)

            sorted_tasks = sorted(tasks_data, key=sort_key)
            optimized_order = [t["task_id"] for t in sorted_tasks]

            return optimized_order

    def get_queue_estimated_completion(self) -> dict:
        """
        Calculate estimated completion times for all queued tasks.

        Returns:
            Dict with task_id -> estimated completion datetime
        """
        from backend.main import storage

        result = {
            "running_tasks": {},
            "queued_tasks": {},
            "total_estimated_seconds": 0
        }

        now = datetime.now()

        # Calculate running task completions
        for task_id, info in self._running_task_info.items():
            if info.estimated_duration:
                remaining = max(0, info.estimated_duration - (now - info.started_at).total_seconds())
                result["running_tasks"][task_id] = {
                    "estimated_completion": (now + timedelta(seconds=remaining)).isoformat(),
                    "remaining_seconds": remaining
                }

        # Calculate queued task completions based on position
        # Assume tasks run in parallel up to max_concurrent
        slot_availability = []  # When each slot becomes available

        # Initialize with running tasks' remaining times
        for task_id, info in self._running_task_info.items():
            if info.estimated_duration:
                remaining = max(0, info.estimated_duration - (now - info.started_at).total_seconds())
                slot_availability.append(remaining)

        # Fill remaining slots as immediately available
        while len(slot_availability) < self.max_concurrent:
            slot_availability.append(0)

        # Process queued tasks
        sorted_queue = sorted(
            self._queued_task_info.values(),
            key=lambda x: (PRIORITY_VALUES[x.priority], x.queued_at)
        )

        for info in sorted_queue:
            estimated_duration = info.estimated_duration or self.estimate_task_duration(info.task_id)

            # Find the earliest available slot
            earliest_slot_time = min(slot_availability)
            slot_idx = slot_availability.index(earliest_slot_time)

            # Task starts when slot is available, completes after its duration
            start_time = earliest_slot_time
            completion_time = start_time + estimated_duration
            slot_availability[slot_idx] = completion_time

            result["queued_tasks"][info.task_id] = {
                "estimated_start": (now + timedelta(seconds=start_time)).isoformat(),
                "estimated_completion": (now + timedelta(seconds=completion_time)).isoformat(),
                "estimated_duration": estimated_duration,
                "wait_time_seconds": start_time
            }

        # Total time until all tasks complete
        if slot_availability:
            result["total_estimated_seconds"] = max(slot_availability)
            result["all_complete_at"] = (now + timedelta(seconds=max(slot_availability))).isoformat()

        return result

    async def update_max_concurrent(self, new_max: int) -> bool:
        """
        Update the maximum concurrent tasks limit.

        Args:
            new_max: New maximum (1-10)

        Returns:
            True if updated successfully
        """
        if not 1 <= new_max <= 10:
            return False

        old_max = self.max_concurrent
        self.max_concurrent = new_max

        # Update semaphore if workers are running
        if self._semaphore:
            # Create a new semaphore with the new limit
            # We need to be careful here - can't change semaphore value directly
            # For now, the change will take effect for new task starts
            print(f"[TaskQueue] Max concurrent updated from {old_max} to {new_max}")

        return True


# Global instance
task_queue = TaskQueue()
