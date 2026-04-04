"""
Shared state management for Ferret web dashboard.
Stores sync status, server info, and recent activity.
"""
from datetime import datetime
from typing import Optional
from collections import deque
import threading


class AppState:
    """Thread-safe application state for the web dashboard."""

    def __init__(self):
        self._lock = threading.Lock()

        # Sync state
        self.is_syncing = False
        self.last_sync_time: Optional[datetime] = None
        self.next_sync_time: Optional[datetime] = None
        self.sync_count = 0
        self.current_operation: Optional[str] = None

        # Dry-run mode flag
        self.dryrun = False

        # Server status
        self.servers = {}  # {server_name: {type, status, version}}

        # Statistics
        self.total_items_synced = 0
        self.total_users = 0

        # Cleanup results
        self.cleanup_results: Optional[dict] = None

        # Recent logs (keep last 1000 lines)
        self.recent_logs = deque(maxlen=1000)

        # Add initial log message
        self.add_log("Web dashboard initialized")

        # Manual sync trigger
        self.manual_sync_requested = False

    def set_dryrun(self, dryrun: bool):
        """Set dry-run mode flag."""
        with self._lock:
            self.dryrun = dryrun

    def set_syncing(self, is_syncing: bool, operation: Optional[str] = None):
        """Set sync status."""
        with self._lock:
            was_syncing = self.is_syncing
            self.is_syncing = is_syncing
            self.current_operation = operation
            if not is_syncing and was_syncing:
                # Only increment when a sync cycle completes
                self.sync_count += 1
                self.last_sync_time = datetime.now()

    def add_server(self, name: str, server_type: str, status: str, version: str = ""):
        """Add or update server information."""
        with self._lock:
            self.servers[name] = {
                "type": server_type,
                "status": status,
                "version": version,
                "last_check": datetime.now()
            }

    def update_stats(self, items_synced: int = 0, users: int = 0):
        """Update sync statistics."""
        with self._lock:
            if items_synced > 0:
                self.total_items_synced += items_synced
            if users > 0:
                self.total_users = users

    def add_log(self, log_line: str):
        """Add a log line to recent logs."""
        with self._lock:
            self.recent_logs.append(log_line)

    def get_logs(self, limit: int = 100) -> list[str]:
        """Get recent log lines."""
        with self._lock:
            return list(self.recent_logs)[-limit:]

    def request_manual_sync(self):
        """Request a manual sync."""
        with self._lock:
            self.manual_sync_requested = True

    def clear_manual_sync_request(self):
        """Clear manual sync request flag."""
        with self._lock:
            self.manual_sync_requested = False

    def set_cleanup_results(self, results: dict):
        """Store cleanup scan results."""
        with self._lock:
            self.cleanup_results = results

    def get_status(self) -> dict:
        """Get current application status."""
        with self._lock:
            # Format last_sync_time to be human readable in local time
            last_sync_formatted = None
            if self.last_sync_time:
                # Get timezone offset from TZ env var or default to UTC
                # Docker containers often need TZ env var set to show correct local time
                last_sync_formatted = self.last_sync_time.strftime("%b %d, %I:%M %p").lstrip('0')

            return {
                "is_syncing": self.is_syncing,
                "dryrun": self.dryrun,
                "last_sync_time": last_sync_formatted,
                "next_sync_time": self.next_sync_time.isoformat() if self.next_sync_time else None,
                "sync_count": self.sync_count,
                "current_operation": self.current_operation,
                "servers": self.servers.copy(),
                "total_items_synced": self.total_items_synced,
                "total_users": self.total_users,
                "cleanup_results": self.cleanup_results,
            }


# Global state instance
app_state = AppState()
