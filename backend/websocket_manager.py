from fastapi import WebSocket
from typing import Dict, List


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, task_id: str):
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = []
        self.active_connections[task_id].append(websocket)

    def disconnect(self, websocket: WebSocket, task_id: str):
        if task_id in self.active_connections:
            if websocket in self.active_connections[task_id]:
                self.active_connections[task_id].remove(websocket)
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]

    async def send_log(self, task_id: str, message: str):
        print(f"[DEBUG] send_log called for task {task_id}, connections: {len(self.active_connections.get(task_id, []))}")
        if task_id in self.active_connections:
            disconnected = []
            for connection in self.active_connections[task_id]:
                try:
                    await connection.send_text(message)
                    print(f"[DEBUG] Message sent to WebSocket: {message[:50]}...")
                except Exception as e:
                    print(f"[DEBUG] Failed to send to WebSocket: {e}")
                    disconnected.append(connection)

            for conn in disconnected:
                self.disconnect(conn, task_id)
        else:
            print(f"[DEBUG] No active connections for task {task_id}")

    async def broadcast(self, task_id: str, message: str):
        await self.send_log(task_id, message)


manager = ConnectionManager()
