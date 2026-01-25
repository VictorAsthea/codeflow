from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pathlib import Path
import logging

from backend.services.json_storage import JSONStorage
from backend.services.migration import run_migration_if_needed
from backend.routers import tasks, settings, git, webhooks, worktrees, roadmap, context, changelog, project
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

    yield

    # Cleanup
    await task_queue.stop_all()
    if pr_monitor_instance:
        await pr_monitor_instance.stop()


app = FastAPI(title="Codeflow", version="0.1.0", lifespan=lifespan)

app.include_router(tasks.router, prefix="/api", tags=["tasks"])
app.include_router(settings.router, prefix="/api", tags=["settings"])
app.include_router(git.router, prefix="/api", tags=["git"])
app.include_router(webhooks.router, prefix="/api", tags=["webhooks"])
app.include_router(worktrees.router, prefix="/api", tags=["worktrees"])
app.include_router(roadmap.router, prefix="/api", tags=["roadmap"])
app.include_router(context.router, tags=["context"])
app.include_router(changelog.router, prefix="/api", tags=["changelog"])
app.include_router(project.router, prefix="/api", tags=["project"])

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
