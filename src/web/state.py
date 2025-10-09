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

        # Server status
        self.servers = {}  # {server_name: {type, status, version}}

        # Statistics
        self.total_items_synced = 0
        self.total_users = 0
        self.backfill_complete = False
        self.backfill_count = 0

        # Recent logs (keep last 1000 lines)
        self.recent_logs = deque(maxlen=1000)

        # Manual sync trigger
        self.manual_sync_requested = False

    def set_syncing(self, is_syncing: bool, operation: Optional[str] = None):
        """Set sync status."""
        with self._lock:
            self.is_syncing = is_syncing
            self.current_operation = operation
            if is_syncing:
                self.sync_count += 1
            else:
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

    def set_backfill_status(self, complete: bool, count: int = 0):
        """Update backfill status."""
        with self._lock:
            self.backfill_complete = complete
            if count > 0:
                self.backfill_count = count

    def add_log(self, log_line: str):
        """Add a log line to recent logs."""
        with self._lock:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.recent_logs.append(f"[{timestamp}] {log_line}")

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

    def get_status(self) -> dict:
        """Get current application status."""
        with self._lock:
            return {
                "is_syncing": self.is_syncing,
                "last_sync_time": self.last_sync_time.isoformat() if self.last_sync_time else None,
                "next_sync_time": self.next_sync_time.isoformat() if self.next_sync_time else None,
                "sync_count": self.sync_count,
                "current_operation": self.current_operation,
                "servers": self.servers.copy(),
                "total_items_synced": self.total_items_synced,
                "total_users": self.total_users,
                "backfill_complete": self.backfill_complete,
                "backfill_count": self.backfill_count,
            }


# Global state instance
app_state = AppState()
