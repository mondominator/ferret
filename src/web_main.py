"""
Main entry point for Ferret with web dashboard.
Runs the sync loop and web server concurrently.
"""
import asyncio
import threading
import uvicorn
from loguru import logger

from src.main import main as sync_main
from src.web.app import app
from src.web.log_handler import WebDashboardHandler


def run_sync_loop():
    """Run the sync loop in a separate thread."""
    try:
        sync_main()
    except Exception as e:
        logger.error(f"Sync loop error: {e}")


def run_web_server():
    """Run the FastAPI web server."""
    logger.info("Web: Starting dashboard on http://0.0.0.0:8080")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="warning",  # Reduce uvicorn noise
    )


def main():
    """Main entry point - runs both sync and web server."""
    # Add custom log handler for web dashboard
    # Use serialize=True to get structured log data
    logger.add(
        WebDashboardHandler(),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        colorize=False,
        serialize=False
    )

    logger.info("Ferret: Starting with web dashboard enabled")

    # Start sync loop in background thread
    sync_thread = threading.Thread(target=run_sync_loop, daemon=True)
    sync_thread.start()

    # Run web server in main thread (blocking)
    try:
        run_web_server()
    except KeyboardInterrupt:
        logger.info("Ferret: Shutting down...")
    except Exception as e:
        logger.error(f"Ferret: Fatal error: {e}")


if __name__ == "__main__":
    main()
