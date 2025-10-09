"""
Custom log handler that feeds logs to the web dashboard.
"""
import re
from src.web.state import app_state


class WebDashboardHandler:
    """Custom loguru handler that sends logs to the web dashboard."""

    def __init__(self):
        """Initialize the handler."""
        # Compile regex for ANSI color codes once
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    def write(self, message):
        """Write log message to dashboard state."""
        if isinstance(message, dict):
            # Loguru passes a dict with 'text' key
            text = message.get('text', '')
        else:
            text = str(message)

        # Remove ANSI color codes and trailing newlines
        clean_message = self.ansi_escape.sub('', text).rstrip('\n')

        if clean_message:
            app_state.add_log(clean_message)

    def flush(self):
        """Flush handler (no-op for our use case)."""
        pass
