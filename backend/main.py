from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from backend.database import init_db
from backend.routers import tasks, settings, git, webhooks
from backend.services.task_queue import task_queue
from backend.services.pr_monitor import PRMonitor
from backend.websocket_manager import manager
from backend.config import settings as app_settings

pr_monitor_instance = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pr_monitor_instance

    await init_db()

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
