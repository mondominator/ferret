import requests
from loguru import logger
from plexapi.video import Movie, Episode


class TautulliWebhook:
    """
    Send custom notifications to Tautulli via webhook.

    NOTE: This does NOT create history entries - only notifications.
    For actual history tracking, use TautulliLogger (direct database writes).
    """

    def __init__(self, tautulli_url: str | None = None, api_key: str | None = None):
        """
        Initialize Tautulli webhook notifier.

        Args:
            tautulli_url: Tautulli base URL (e.g., http://localhost:8181)
            api_key: Tautulli API key
        """
        self.enabled = tautulli_url and api_key
        self.url = f"{tautulli_url}/api/v2" if tautulli_url else None
        self.api_key = api_key

        if self.enabled:
            logger.info(f"Tautulli: Webhook notifications enabled to {tautulli_url}")

    def notify_watch(
        self,
        item: Movie | Episode,
        user_name: str,
        server_name: str,
    ) -> None:
        """
        Send a custom notification to Tautulli about a watch event.

        Args:
            item: The Movie or Episode that was watched
            user_name: Plex username
            server_name: Plex server name
        """
        if not self.enabled:
            return

        try:
            media_type = "movie" if hasattr(item, "year") and not hasattr(item, "grandparentTitle") else "episode"

            # Use Tautulli's notify API
            params = {
                "apikey": self.api_key,
                "cmd": "notify",
                "notifier_id": 1,  # Custom script notifier
                "subject": "Ferret Sync",
                "body": f"{user_name} watched {item.title} on {server_name} (synced from external server)",
            }

            response = requests.get(self.url, params=params, timeout=10)
            response.raise_for_status()

            logger.debug(f"Tautulli: Sent notification for {item.title}")

        except Exception as e:
            logger.warning(f"Tautulli: Failed to send notification: {e}")
