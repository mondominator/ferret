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
    from dotenv import dotenv_values
    from src.functions import get_env_value, str_to_bool

    env_file = get_env_value(None, "ENV_FILE", ".env")
    config = dotenv_values(env_file)
    tautulli_enabled = str_to_bool(get_env_value(config, "TAUTULLI_BACKFILL_ENABLED", "False"))

    status = app_state.get_status()
    status["tautulli_enabled"] = tautulli_enabled

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "status": status}
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
        {"request": request, "config": config, "status": app_state.get_status()}
    )


@app.post("/api/settings/save")
async def save_settings(request: Request):
    """Save settings to .env file."""
    try:
        import re
        data = await request.json()
        from src.functions import get_env_value

        # --- Input validation ---
        errors = []

        # SLEEP_DURATION must be a positive integer
        sleep_val = data.get("SLEEP_DURATION", "")
        if sleep_val:
            try:
                sleep_int = int(sleep_val)
                if sleep_int <= 0:
                    errors.append("SLEEP_DURATION must be a positive integer")
            except (ValueError, TypeError):
                errors.append("SLEEP_DURATION must be a valid integer")

        # REQUEST_TIMEOUT must be a positive integer
        timeout_val = data.get("REQUEST_TIMEOUT", "")
        if timeout_val:
            try:
                timeout_int = int(timeout_val)
                if timeout_int <= 0:
                    errors.append("REQUEST_TIMEOUT must be a positive integer")
            except (ValueError, TypeError):
                errors.append("REQUEST_TIMEOUT must be a valid integer")

        # MAX_THREADS must be a positive integer
        threads_val = data.get("MAX_THREADS", "")
        if threads_val:
            try:
                threads_int = int(threads_val)
                if threads_int <= 0:
                    errors.append("MAX_THREADS must be a positive integer")
            except (ValueError, TypeError):
                errors.append("MAX_THREADS must be a valid integer")

        # URL fields must look like URLs (http/https) if non-empty
        url_pattern = re.compile(r'^https?://.+')
        for url_key in ("PLEX_BASEURL", "JELLYFIN_BASEURL", "EMBY_BASEURL"):
            url_val = data.get(url_key, "").strip()
            if url_val:
                # Support comma-separated URLs
                for single_url in url_val.split(","):
                    single_url = single_url.strip()
                    if single_url and not url_pattern.match(single_url):
                        errors.append(f"{url_key} must start with http:// or https:// (got: {single_url})")

        # USER_MAPPING must be valid JSON if non-empty
        user_mapping_val = data.get("USER_MAPPING", "").strip()
        if user_mapping_val:
            try:
                import json
                json.loads(user_mapping_val)
            except (json.JSONDecodeError, TypeError):
                errors.append("USER_MAPPING must be valid JSON")

        if errors:
            return {"success": False, "message": "; ".join(errors)}

        # --- Save validated settings ---
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
        return {"success": True, "message": "Settings saved. Changes will take effect on the next sync cycle."}
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
    from dotenv import dotenv_values
    from src.functions import get_env_value, str_to_bool

    env_file = get_env_value(None, "ENV_FILE", ".env")
    config = dotenv_values(env_file)
    tautulli_enabled = str_to_bool(get_env_value(config, "TAUTULLI_BACKFILL_ENABLED", "False"))

    status = app_state.get_status()
    status["tautulli_enabled"] = tautulli_enabled

    return templates.TemplateResponse(
        "partials/status_header.html",
        {"request": request, "status": status}
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

        # Track position by index into the deque so duplicate lines aren't dropped
        last_sent_index = len(app_state.recent_logs)

        while True:
            await asyncio.sleep(0.5)

            current_logs = list(app_state.recent_logs)
            current_len = len(current_logs)

            if current_len < last_sent_index:
                # Deque was trimmed/reset; send everything and reset index
                new_logs = current_logs
                last_sent_index = current_len
            else:
                new_logs = current_logs[last_sent_index:]
                last_sent_index = current_len

            if new_logs:
                for log_line in new_logs:
                    await websocket.send_text(log_line)

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
