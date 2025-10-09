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


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings page."""
    from dotenv import dotenv_values
    from src.functions import get_env_value

    env_file = get_env_value(None, "ENV_FILE", ".env")
    config = dotenv_values(env_file)

    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "config": config}
    )


@app.post("/api/settings/save")
async def save_settings(request: Request):
    """Save settings to .env file."""
    try:
        data = await request.json()
        from src.functions import get_env_value

        env_file = get_env_value(None, "ENV_FILE", ".env")

        # Read existing .env
        with open(env_file, 'r') as f:
            lines = f.readlines()

        # Update values
        updated_lines = []
        keys_updated = set()

        for line in lines:
            updated = False
            for key, value in data.items():
                if line.strip().startswith(f"{key} =") or line.strip().startswith(f"{key}="):
                    updated_lines.append(f'{key} = "{value}"\n')
                    keys_updated.add(key)
                    updated = True
                    break
            if not updated:
                updated_lines.append(line)

        # Write back to .env
        with open(env_file, 'w') as f:
            f.writelines(updated_lines)

        logger.info("Settings saved successfully")
        return {"success": True, "message": "Settings saved"}
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")
        return {"success": False, "message": str(e)}


@app.get("/api/status")
async def get_status():
    """Get current application status (JSON)."""
    return app_state.get_status()


@app.get("/api/status/card", response_class=HTMLResponse)
async def get_status_card(request: Request):
    """Get status card HTML for htmx updates."""
    return templates.TemplateResponse(
        "partials/status_card.html",
        {"request": request, "status": app_state.get_status()}
    )


@app.get("/api/status/footer", response_class=HTMLResponse)
async def get_status_footer(request: Request):
    """Get status footer HTML for htmx updates."""
    return templates.TemplateResponse(
        "partials/status_footer.html",
        {"request": request, "status": app_state.get_status()}
    )


@app.get("/api/status/header", response_class=HTMLResponse)
async def get_status_header(request: Request):
    """Get status header HTML for htmx updates."""
    return templates.TemplateResponse(
        "partials/status_header.html",
        {"request": request, "status": app_state.get_status()}
    )


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
        logger.info(f"Web: Sending {len(recent_logs)} recent logs to client")
        for log_line in recent_logs:
            await websocket.send_text(log_line)

        # Keep connection alive and send new logs
        # Track the last log we sent to detect new ones
        sent_logs = set(recent_logs)

        while True:
            await asyncio.sleep(0.5)  # Check more frequently

            # Check for new logs by comparing with what we've sent
            current_logs = list(app_state.recent_logs)
            new_logs = [log for log in current_logs if log not in sent_logs]

            if new_logs:
                logger.debug(f"Web: Sending {len(new_logs)} new logs to client")
                for log_line in new_logs:
                    await websocket.send_text(log_line)
                    sent_logs.add(log_line)

                # Keep sent_logs from growing too large
                if len(sent_logs) > 1000:
                    sent_logs = set(current_logs[-500:])

    except WebSocketDisconnect:
        logger.info("Web: Log viewer WebSocket disconnected")
    except Exception as e:
        logger.error(f"Web: WebSocket error: {e}")


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "ferret"}


@app.get("/api/debug/state")
async def debug_state():
    """Debug endpoint to see current state."""
    return {
        "log_count": len(app_state.recent_logs),
        "server_count": len(app_state.servers),
        "servers": app_state.servers,
        "status": app_state.get_status(),
        "recent_logs_sample": list(app_state.recent_logs)[-10:] if app_state.recent_logs else []
    }
