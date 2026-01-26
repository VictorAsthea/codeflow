from fastapi import WebSocket
from typing import Dict, List, Optional, Set
import json
import asyncio
import time
import threading
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class EnhancedConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.thinking_states: Dict[str, bool] = {}
        self.last_activity: Dict[str, float] = {}
        self.message_buffer: Dict[str, List[dict]] = {}
        self.buffer_size = 100

    async def connect(self, websocket: WebSocket, task_id: str):
        """Enhanced connection with buffer replay capability"""
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = []
        self.active_connections[task_id].append(websocket)

        # Initialize tracking
        self.last_activity[task_id] = time.time()
        if task_id not in self.thinking_states:
            self.thinking_states[task_id] = False

        # Send buffered messages to new connection
        if task_id in self.message_buffer:
            for buffered_message in self.message_buffer[task_id]:
                try:
                    await websocket.send_text(json.dumps(buffered_message, cls=DateTimeEncoder))
                except Exception as e:
                    logger.warning(f"Failed to send buffered message: {e}")

        logger.info(f"WebSocket connected for task {task_id}, total connections: {len(self.active_connections[task_id])}")

    def disconnect(self, websocket: WebSocket, task_id: str):
        """Enhanced disconnect with cleanup"""
        if task_id in self.active_connections:
            if websocket in self.active_connections[task_id]:
                self.active_connections[task_id].remove(websocket)
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]
                # Clean up tracking data
                self.thinking_states.pop(task_id, None)
                self.last_activity.pop(task_id, None)
                # Keep buffer for potential reconnection
                logger.info(f"All connections closed for task {task_id}")

        logger.info(f"WebSocket disconnected for task {task_id}")

    async def send_log(self, task_id: str, message: str):
        """Enhanced log sending with enriched metadata"""
        await self.send_enriched_log(task_id, {
            "type": "log",
            "content": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw": message
        })

    async def send_enriched_log(self, task_id: str, log_data: dict):
        """Send enriched log with metadata and buffering"""
        # Update activity tracking
        self.last_activity[task_id] = time.time()

        # Add to buffer
        self._buffer_message(task_id, log_data)

        # Send to all active connections
        if task_id in self.active_connections:
            disconnected = []
            message_json = json.dumps(log_data, cls=DateTimeEncoder)

            for connection in self.active_connections[task_id]:
                try:
                    await connection.send_text(message_json)
                    logger.debug(f"Enriched log sent to WebSocket for task {task_id}")
                except Exception as e:
                    logger.warning(f"Failed to send to WebSocket: {e}")
                    disconnected.append(connection)

            # Clean up disconnected clients
            for conn in disconnected:
                self.disconnect(conn, task_id)
        else:
            logger.debug(f"No active connections for task {task_id}, message buffered")

    async def send_tool_call_live(self, task_id: str, tool_call: dict):
        """Send live tool call with enhanced metadata"""
        enriched_tool = {
            "type": "tool_call",
            "tool_name": tool_call.get("tool", "unknown"),
            "tool_type": self._classify_tool_type(tool_call.get("tool", "")),
            "parameters": tool_call.get("parameters", {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "starting",
            "icon": self._get_tool_icon(tool_call.get("tool", ""))
        }
        await self.send_enriched_log(task_id, enriched_tool)

    async def send_thinking_indicator(self, task_id: str, is_thinking: bool):
        """Send thinking state indicator"""
        if self.thinking_states.get(task_id) != is_thinking:
            self.thinking_states[task_id] = is_thinking

            thinking_data = {
                "type": "thinking",
                "is_thinking": is_thinking,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": "Agent is thinking..." if is_thinking else "Agent response ready"
            }
            await self.send_enriched_log(task_id, thinking_data)

    async def send_tool_result(self, task_id: str, tool_name: str, result: dict, success: bool = True):
        """Send tool execution result"""
        tool_result = {
            "type": "tool_result",
            "tool_name": tool_name,
            "tool_type": self._classify_tool_type(tool_name),
            "success": success,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result_summary": str(result)[:200] + "..." if len(str(result)) > 200 else str(result),
            "icon": self._get_tool_icon(tool_name)
        }
        await self.send_enriched_log(task_id, tool_result)

    async def broadcast(self, task_id: str, message: str):
        await self.send_log(task_id, message)

    async def send_progress_update(self, task_id: str, phase_name: str, metrics: dict):
        """
        Send progress update for a specific phase

        Args:
            task_id: Task identifier
            phase_name: Name of the phase (planning, coding, validation)
            metrics: Dictionary containing progress metrics
        """
        progress_data = {
            "type": "progress_update",
            "phase": phase_name,
            "metrics": metrics,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await self.send_enriched_log(task_id, progress_data)

    def _buffer_message(self, task_id: str, log_data: dict):
        """Add message to circular buffer"""
        if task_id not in self.message_buffer:
            self.message_buffer[task_id] = []

        # Add to buffer
        self.message_buffer[task_id].append(log_data)

        # Maintain buffer size
        if len(self.message_buffer[task_id]) > self.buffer_size:
            self.message_buffer[task_id].pop(0)

    def _classify_tool_type(self, tool_name: str) -> str:
        """Classify tool into categories for filtering"""
        tool_lower = tool_name.lower()

        if any(t in tool_lower for t in ["read", "grep", "glob", "search"]):
            return "read"
        elif any(t in tool_lower for t in ["edit", "write", "create"]):
            return "write"
        elif any(t in tool_lower for t in ["bash", "shell", "command", "execute"]):
            return "bash"
        elif any(t in tool_lower for t in ["task", "agent"]):
            return "tool"
        elif any(t in tool_lower for t in ["error", "fail", "exception"]):
            return "error"
        else:
            return "info"

    def _get_tool_icon(self, tool_name: str) -> str:
        """Get icon for tool type"""
        tool_type = self._classify_tool_type(tool_name)

        icons = {
            "read": "📖",
            "write": "✏️",
            "bash": "⚡",
            "tool": "🔧",
            "error": "❌",
            "info": "ℹ️"
        }

        return icons.get(tool_type, "🔧")

    async def get_task_status(self, task_id: str) -> dict:
        """Get current status information for a task"""
        return {
            "task_id": task_id,
            "active_connections": len(self.active_connections.get(task_id, [])),
            "is_thinking": self.thinking_states.get(task_id, False),
            "last_activity": self.last_activity.get(task_id),
            "buffer_size": len(self.message_buffer.get(task_id, []))
        }


# Create enhanced manager instance (backward compatibility alias)
manager = EnhancedConnectionManager()

# Backward compatibility alias
ConnectionManager = EnhancedConnectionManager


class KanbanConnectionManager:
    """
    WebSocket manager for broadcasting kanban-wide events (archive, unarchive, etc.)
    to all connected clients for real-time UI sync.
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = threading.Lock()

    async def connect(self, websocket: WebSocket):
        """Accept and track a new WebSocket connection"""
        await websocket.accept()
        with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"Kanban WebSocket connected, total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"Kanban WebSocket disconnected, total: {len(self.active_connections)}")

    async def broadcast(self, event_type: str, data: dict):
        """
        Broadcast an event to all connected clients.

        Args:
            event_type: Type of event (e.g., 'task_archived', 'task_unarchived')
            data: Event payload containing relevant task data
        """
        message = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        message_json = json.dumps(message, cls=DateTimeEncoder)

        with self._lock:
            connections_to_send = list(self.active_connections)

        disconnected = []
        for connection in connections_to_send:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.warning(f"Failed to send to kanban WebSocket: {e}")
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

        if self.active_connections:
            logger.debug(f"Broadcast {event_type} to {len(self.active_connections)} clients")

    async def broadcast_task_archived(self, task_id: str, task_data: dict = None):
        """Broadcast task archived event"""
        await self.broadcast("task_archived", {
            "task_id": task_id,
            "task": task_data
        })

    async def broadcast_task_unarchived(self, task_id: str, task_data: dict = None):
        """Broadcast task unarchived event"""
        await self.broadcast("task_unarchived", {
            "task_id": task_id,
            "task": task_data
        })


# Global kanban manager instance
kanban_manager = KanbanConnectionManager()


class ParallelExecutionManager:
    """
    Global manager for tracking all parallel task executions across worktrees.
    Provides aggregate status updates for parallel execution monitoring dashboard.
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = threading.Lock()
        # Track running tasks with their latest progress info
        self._running_tasks: Dict[str, dict] = {}
        # Track task events for real-time updates
        self._task_events: Dict[str, List[dict]] = {}
        self._event_buffer_size = 50  # Keep last 50 events per task

    async def connect(self, websocket: WebSocket):
        """Accept and track a new WebSocket connection for parallel status updates"""
        await websocket.accept()
        with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"Parallel status WebSocket connected, total: {len(self.active_connections)}")

        # Send current state to new connection
        await self._send_initial_state(websocket)

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"Parallel status WebSocket disconnected, total: {len(self.active_connections)}")

    async def _send_initial_state(self, websocket: WebSocket):
        """Send current state to newly connected client"""
        try:
            state = {
                "type": "initial_state",
                "running_tasks": self.get_all_running_tasks(),
                "aggregate_progress": self.get_aggregate_progress(),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await websocket.send_text(json.dumps(state, cls=DateTimeEncoder))
        except Exception as e:
            logger.warning(f"Failed to send initial state: {e}")

    def register_task(self, task_id: str, task_info: dict):
        """
        Register a new task as running.

        Args:
            task_id: Unique task identifier
            task_info: Initial task info (title, worktree_path, phase, etc.)
        """
        with self._lock:
            self._running_tasks[task_id] = {
                "task_id": task_id,
                "title": task_info.get("title", "Unknown"),
                "worktree_path": task_info.get("worktree_path"),
                "current_phase": task_info.get("current_phase", "planning"),
                "current_subtask": task_info.get("current_subtask"),
                "progress_percentage": 0,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "last_activity": datetime.now(timezone.utc).isoformat(),
                **task_info
            }
            self._task_events[task_id] = []
        logger.info(f"Task {task_id} registered in parallel manager")

    def unregister_task(self, task_id: str, final_status: str = "completed"):
        """
        Remove a task from tracking when it completes or fails.

        Args:
            task_id: Task identifier
            final_status: Final status (completed, failed, cancelled)
        """
        with self._lock:
            if task_id in self._running_tasks:
                del self._running_tasks[task_id]
            if task_id in self._task_events:
                del self._task_events[task_id]
        logger.info(f"Task {task_id} unregistered from parallel manager (status: {final_status})")

    def update_task_progress(self, task_id: str, progress_data: dict):
        """
        Update progress information for a running task.

        Args:
            task_id: Task identifier
            progress_data: Progress info (phase, subtask, percentage, etc.)
        """
        with self._lock:
            if task_id in self._running_tasks:
                self._running_tasks[task_id].update(progress_data)
                self._running_tasks[task_id]["last_activity"] = datetime.now(timezone.utc).isoformat()

    def add_task_event(self, task_id: str, event: dict):
        """
        Add an event to a task's event log.

        Args:
            task_id: Task identifier
            event: Event data (type, message, timestamp, etc.)
        """
        with self._lock:
            if task_id not in self._task_events:
                self._task_events[task_id] = []

            event_with_timestamp = {
                **event,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            self._task_events[task_id].append(event_with_timestamp)

            # Keep buffer limited
            if len(self._task_events[task_id]) > self._event_buffer_size:
                self._task_events[task_id].pop(0)

    def get_all_running_tasks(self) -> List[dict]:
        """
        Get information about all currently running tasks.

        Returns:
            List of task info dictionaries with progress details
        """
        with self._lock:
            return list(self._running_tasks.values())

    def get_aggregate_progress(self) -> dict:
        """
        Calculate aggregate progress across all running tasks.

        Returns:
            Dictionary with aggregate metrics:
            - total_tasks: Number of running tasks
            - by_phase: Count of tasks per phase
            - average_progress: Average progress percentage
            - tasks_summary: Brief summary per task
        """
        with self._lock:
            tasks = list(self._running_tasks.values())

        if not tasks:
            return {
                "total_tasks": 0,
                "by_phase": {},
                "average_progress": 0,
                "tasks_summary": []
            }

        # Count by phase
        by_phase = {}
        total_progress = 0

        for task in tasks:
            phase = task.get("current_phase", "unknown")
            by_phase[phase] = by_phase.get(phase, 0) + 1
            total_progress += task.get("progress_percentage", 0)

        # Create summary
        tasks_summary = [
            {
                "task_id": t.get("task_id"),
                "title": t.get("title", "")[:50],  # Truncate for summary
                "phase": t.get("current_phase"),
                "progress": t.get("progress_percentage", 0)
            }
            for t in tasks
        ]

        return {
            "total_tasks": len(tasks),
            "by_phase": by_phase,
            "average_progress": total_progress / len(tasks) if tasks else 0,
            "tasks_summary": tasks_summary
        }

    async def broadcast_queue_update(self, event_type: str, data: dict):
        """
        Broadcast a queue update event to all connected clients.

        Args:
            event_type: Type of event (task_started, task_completed, phase_changed, etc.)
            data: Event payload
        """
        message = {
            "type": event_type,
            "data": data,
            "aggregate": self.get_aggregate_progress(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        message_json = json.dumps(message, cls=DateTimeEncoder)

        with self._lock:
            connections_to_send = list(self.active_connections)

        disconnected = []
        for connection in connections_to_send:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.warning(f"Failed to send to parallel status WebSocket: {e}")
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

        if self.active_connections:
            logger.debug(f"Broadcast {event_type} to {len(self.active_connections)} parallel status clients")

    async def notify_task_started(self, task_id: str, task_info: dict):
        """Notify clients that a new task has started execution"""
        self.register_task(task_id, task_info)
        await self.broadcast_queue_update("task_started", {
            "task_id": task_id,
            "task_info": task_info
        })

    async def notify_task_completed(self, task_id: str, result: dict = None):
        """Notify clients that a task has completed"""
        self.unregister_task(task_id, "completed")
        await self.broadcast_queue_update("task_completed", {
            "task_id": task_id,
            "result": result or {}
        })

    async def notify_task_failed(self, task_id: str, error: str = None):
        """Notify clients that a task has failed"""
        self.unregister_task(task_id, "failed")
        await self.broadcast_queue_update("task_failed", {
            "task_id": task_id,
            "error": error
        })

    async def notify_phase_changed(self, task_id: str, phase: str, metrics: dict = None):
        """Notify clients that a task has changed phase"""
        self.update_task_progress(task_id, {
            "current_phase": phase,
            "phase_metrics": metrics or {}
        })
        await self.broadcast_queue_update("phase_changed", {
            "task_id": task_id,
            "phase": phase,
            "metrics": metrics or {}
        })

    async def notify_subtask_progress(self, task_id: str, subtask_info: dict, progress: dict):
        """Notify clients about subtask progress"""
        self.update_task_progress(task_id, {
            "current_subtask": subtask_info.get("title"),
            "current_subtask_id": subtask_info.get("id"),
            "progress_percentage": progress.get("percentage", 0)
        })
        await self.broadcast_queue_update("subtask_progress", {
            "task_id": task_id,
            "subtask": subtask_info,
            "progress": progress
        })

    async def notify_queue_changed(self, queue_status: dict):
        """Notify clients that the queue status has changed"""
        await self.broadcast_queue_update("queue_changed", queue_status)


# Global parallel execution manager instance
parallel_manager = ParallelExecutionManager()
