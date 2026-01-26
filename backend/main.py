from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from pathlib import Path
import logging

from backend.services.json_storage import JSONStorage


# =============================================================================
# SECURITY MIDDLEWARE
# =============================================================================
# Request body size limits to prevent denial-of-service attacks via large payloads.
# - Regular API requests: 1MB (1,048,576 bytes)
# - File uploads: 10MB (10,485,760 bytes) - reserved for future use
# =============================================================================

# Maximum request body sizes in bytes
MAX_BODY_SIZE = 1 * 1024 * 1024  # 1MB for regular requests
MAX_FILE_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB for file uploads (if any)


class RequestBodySizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce request body size limits.

    Security: Prevents denial-of-service attacks by rejecting requests
    with bodies larger than the configured maximum size.

    This middleware checks the Content-Length header before reading the body,
    providing early rejection of oversized requests.
    """

    def __init__(self, app, max_body_size: int = MAX_BODY_SIZE):
        super().__init__(app)
        self.max_body_size = max_body_size

    async def dispatch(self, request: Request, call_next):
        # Check Content-Length header if present
        content_length = request.headers.get("content-length")

        if content_length:
            try:
                length = int(content_length)
                if length > self.max_body_size:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": f"Request body too large. Maximum size is {self.max_body_size // (1024 * 1024)}MB."
                        }
                    )
            except ValueError:
                # Invalid Content-Length header - let the request proceed
                # and fail naturally if the body is actually too large
                pass

        return await call_next(request)


from backend.services.migration import run_migration_if_needed
from backend.routers import tasks, settings, git, webhooks, worktrees, roadmap, context, changelog, project, workspace, memory, ideation, auth
from backend.services.task_queue import task_queue
from backend.services.pr_monitor import PRMonitor
from backend.websocket_manager import manager, kanban_manager
from backend.config import settings as app_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

pr_monitor_instance = None

logger = logging.getLogger(__name__)

# Global storage instance
storage = JSONStorage()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pr_monitor_instance

    # Run migration if needed (SQLite to JSON)
    db_path = Path("./data/codeflow.db")
    migration_result = await run_migration_if_needed(db_path, storage)

    if migration_result.get("migrated"):
        logger.info(
            f"Migrated {migration_result.get('tasks_count', 0)} tasks from SQLite to JSON"
        )

    # Setup task queue with executor and start workers
    task_queue.set_executor(tasks.execute_task_background)
    await task_queue.start_workers()

    # Start PR monitoring if enabled
    if app_settings.pr_monitoring_enabled:
        pr_monitor_instance = PRMonitor(
            project_path=app_settings.project_path,
            check_interval=app_settings.pr_check_interval
        )
        await pr_monitor_instance.start()

    # Ensure workspace has at least one project
    from backend.services.workspace_service import get_workspace_service
    ws = get_workspace_service()
    ws.ensure_default_project(app_settings.project_path)

    yield

    # Cleanup
    await task_queue.stop_all()
    if pr_monitor_instance:
        await pr_monitor_instance.stop()


app = FastAPI(title="Codeflow", version="0.1.0", lifespan=lifespan)

# =============================================================================
# MIDDLEWARE STACK
# =============================================================================
# Order matters: middleware is executed in reverse order of registration.
# Request body size limit is added first to reject oversized requests early.
# =============================================================================
app.add_middleware(RequestBodySizeLimitMiddleware, max_body_size=MAX_BODY_SIZE)

app.include_router(tasks.router, prefix="/api", tags=["tasks"])
app.include_router(settings.router, prefix="/api", tags=["settings"])
app.include_router(git.router, prefix="/api", tags=["git"])
app.include_router(webhooks.router, prefix="/api", tags=["webhooks"])
app.include_router(worktrees.router, prefix="/api", tags=["worktrees"])
app.include_router(roadmap.router, prefix="/api", tags=["roadmap"])
app.include_router(context.router, tags=["context"])
app.include_router(changelog.router, prefix="/api", tags=["changelog"])
app.include_router(project.router, prefix="/api", tags=["project"])
app.include_router(workspace.router, prefix="/api", tags=["workspace"])
app.include_router(memory.router, prefix="/api", tags=["memory"])
app.include_router(ideation.router, prefix="/api", tags=["ideation"])
app.include_router(auth.router, prefix="/api", tags=["auth"])

app.mount("/css", StaticFiles(directory="frontend/css"), name="css")
app.mount("/js", StaticFiles(directory="frontend/js"), name="js")


@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


@app.websocket("/ws/logs/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    await manager.connect(websocket, task_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, task_id)


@app.websocket("/ws/kanban")
async def kanban_websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for kanban-wide events (archive, unarchive, etc.)"""
    await kanban_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        kanban_manager.disconnect(websocket)


@app.websocket("/ws/ideation")
async def ideation_websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for ideation chat with streaming responses.
    Receives messages from client and streams AI responses back.
    """
    from backend.routers.ideation import ideation_chat_manager
    from backend.services.ideation_service import get_ideation_service
    from backend.services.storage_manager import get_active_project_path
    import json
    from datetime import datetime, timezone

    await ideation_chat_manager.connect(websocket)

    project_path = get_active_project_path() or app_settings.project_path
    service = get_ideation_service(project_path)

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            try:
                message_data = json.loads(data)
                user_message = message_data.get("message", "")
            except json.JSONDecodeError:
                user_message = data

            if not user_message:
                continue

            # Send acknowledgment
            await ideation_chat_manager.send_message(websocket, {
                "type": "user_message",
                "content": user_message,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

            # Stream response
            chunks = []

            async def on_output(chunk: str):
                chunks.append(chunk)
                await ideation_chat_manager.send_message(websocket, {
                    "type": "stream",
                    "content": chunk,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

            # Get AI response with streaming
            response = await service.chat(user_message, on_output=on_output)

            # Send completion message
            await ideation_chat_manager.send_message(websocket, {
                "type": "complete",
                "content": response,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

    except WebSocketDisconnect:
        ideation_chat_manager.disconnect(websocket)
