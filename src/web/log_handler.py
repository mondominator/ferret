"""
Custom log handler that feeds logs to the web dashboard.
"""
from src.web.state import app_state


class WebDashboardHandler:
    """Custom loguru handler that sends logs to the web dashboard."""

    def write(self, message: str):
        """Write log message to dashboard state."""
        # Remove ANSI color codes
        import re
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        clean_message = ansi_escape.sub('', message).strip()

        if clean_message:
            app_state.add_log(clean_message)

    def flush(self):
        """Flush handler (no-op for our use case)."""
        pass
