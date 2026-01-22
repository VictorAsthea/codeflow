import uvicorn
import webbrowser
import asyncio
from pathlib import Path
from backend.database import init_db


async def setup():
    print("🔧 Initializing database...")
    await init_db()
    print("✅ Database ready")


def open_browser():
    webbrowser.open("http://127.0.0.1:8765")


if __name__ == "__main__":
    asyncio.run(setup())

    print("🚀 Starting Codeflow on http://127.0.0.1:8765")
    print("📝 Press Ctrl+C to stop")

    import threading
    threading.Timer(1.5, open_browser).start()

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8765, reload=True)
