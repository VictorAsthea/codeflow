from fastapi import WebSocket
from typing import Dict, List, Optional
import json
import asyncio
import time
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


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
                    await websocket.send_text(json.dumps(buffered_message))
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
            message_json = json.dumps(log_data)

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
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept and track a new WebSocket connection"""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Kanban WebSocket connected, total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
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
        message_json = json.dumps(message)

        disconnected = []
        for connection in self.active_connections:
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
