"""
FastAPI web application for Ferret dashboard.
"""
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import asyncio
from loguru import logger

from src.web.state import app_state

# Get the project root directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent

app = FastAPI(title="Ferret Dashboard", version="1.0.0")

# Mount static files and templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "status": app_state.get_status()}
    )


@app.get("/api/status")
async def get_status():
    """Get current application status."""
    return app_state.get_status()


@app.get("/api/logs")
async def get_logs(limit: int = 100):
    """Get recent log lines."""
    return {"logs": app_state.get_logs(limit)}


@app.post("/api/sync/trigger")
async def trigger_sync():
    """Manually trigger a sync."""
    if app_state.is_syncing:
        return {"success": False, "message": "Sync already in progress"}

    app_state.request_manual_sync()
    logger.info("Web: Manual sync requested via dashboard")
    return {"success": True, "message": "Sync triggered"}


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket endpoint for real-time logs."""
    await websocket.accept()
    logger.info("Web: Log viewer WebSocket connected")

    try:
        # Send recent logs first
        recent_logs = app_state.get_logs(100)
        for log_line in recent_logs:
            await websocket.send_text(log_line)

        # Keep connection alive and send new logs
        last_log_count = len(app_state.recent_logs)
        while True:
            await asyncio.sleep(1)

            # Check for new logs
            current_log_count = len(app_state.recent_logs)
            if current_log_count > last_log_count:
                # Send new logs
                new_logs = app_state.get_logs(current_log_count - last_log_count)
                for log_line in new_logs:
                    await websocket.send_text(log_line)
                last_log_count = current_log_count

    except WebSocketDisconnect:
        logger.info("Web: Log viewer WebSocket disconnected")
    except Exception as e:
        logger.error(f"Web: WebSocket error: {e}")


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "ferret"}
