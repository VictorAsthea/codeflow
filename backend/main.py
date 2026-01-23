from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pathlib import Path
import logging

from backend.services.json_storage import JSONStorage
from backend.services.migration import run_migration_if_needed
from backend.routers import tasks, settings, git
from backend.services.task_queue import task_queue
from backend.websocket_manager import manager

logger = logging.getLogger(__name__)

# Global storage instance
storage = JSONStorage()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run migration if needed
    db_path = Path("./data/codeflow.db")
    migration_result = await run_migration_if_needed(db_path, storage)

    if migration_result.get("migrated"):
        logger.info(
            f"Migrated {migration_result.get('tasks_count', 0)} tasks from SQLite to JSON"
        )

    # Setup task queue with executor and start workers
    task_queue.set_executor(tasks.execute_task_background)
    await task_queue.start_workers()

    yield

    # Cleanup
    await task_queue.stop_all()


app = FastAPI(title="Codeflow", version="0.1.0", lifespan=lifespan)

app.include_router(tasks.router, prefix="/api", tags=["tasks"])
app.include_router(settings.router, prefix="/api", tags=["settings"])
app.include_router(git.router, prefix="/api", tags=["git"])

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
