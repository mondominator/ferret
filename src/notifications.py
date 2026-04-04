"""
Telegram notifications for Ferret cleanup events.
"""

import requests
from loguru import logger
from src.functions import get_env_value, str_to_bool


class TelegramNotifier:
    """Sends cleanup event notifications via Telegram Bot API."""

    def __init__(self, env):
        self.enabled = str_to_bool(get_env_value(env, "TELEGRAM_ENABLED", "False"))
        self.bot_token = get_env_value(env, "TELEGRAM_BOT_TOKEN", "")
        self.chat_id = get_env_value(env, "TELEGRAM_CHAT_ID", "")

        if self.enabled and (not self.bot_token or not self.chat_id):
            logger.warning("TELEGRAM: Enabled but missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
            self.enabled = False

    def _send(self, text: str) -> bool:
        """Send an HTML-formatted message to the configured chat."""
        if not self.enabled:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            resp = requests.post(url, json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=15)
            if resp.status_code != 200:
                logger.error(f"TELEGRAM: Failed to send ({resp.status_code}): {resp.text}")
                return False
            return True
        except Exception as e:
            logger.error(f"TELEGRAM: Send failed: {e}")
            return False

    def notify_newly_flagged(self, items: list[dict]) -> None:
        """Notify about newly flagged items."""
        if not self.enabled or not items:
            return

        count = len(items)
        shows = [i for i in items if i.get("media_type") == "show"]
        movies = [i for i in items if i.get("media_type") == "movie"]

        lines = [f"<b>🔍 {count} new item{'s' if count != 1 else ''} flagged for cleanup</b>"]
        lines.append("")

        if shows:
            lines.append(f"<b>Shows ({len(shows)})</b>")
            for item in shows[:10]:
                reason = item.get("reason", "")
                lines.append(f"  • {item['title']}" + (f" — <i>{reason}</i>" if reason else ""))
            if len(shows) > 10:
                lines.append(f"  <i>...and {len(shows) - 10} more</i>")

        if movies:
            if shows:
                lines.append("")
            lines.append(f"<b>Movies ({len(movies)})</b>")
            for item in movies[:10]:
                reason = item.get("reason", "")
                lines.append(f"  • {item['title']}" + (f" — <i>{reason}</i>" if reason else ""))
            if len(movies) > 10:
                lines.append(f"  <i>...and {len(movies) - 10} more</i>")

        lines.append("")
        lines.append("30 days until deletion. Exclude from the dashboard if needed.")

        self._send("\n".join(lines))

    def notify_deletion_warning(self, items: list[dict]) -> None:
        """Notify about items 7 days or less from deletion."""
        if not self.enabled or not items:
            return

        count = len(items)
        lines = [f"<b>⚠️ {count} item{'s' if count != 1 else ''} will be deleted within 7 days</b>"]
        lines.append("")

        for item in items[:15]:
            days = item.get("days_until_deletion", "?")
            lines.append(f"  • {item['title']} — <b>{days}d remaining</b>")
        if len(items) > 15:
            lines.append(f"  <i>...and {len(items) - 15} more</i>")

        lines.append("")
        lines.append("Exclude from the dashboard to prevent deletion.")

        self._send("\n".join(lines))

    def notify_deleted(self, titles: list[str]) -> None:
        """Notify about items that were just deleted."""
        if not self.enabled or not titles:
            return

        count = len(titles)
        lines = [f"<b>🗑 Deleted {count} item{'s' if count != 1 else ''}</b>"]
        lines.append("")

        for title in titles[:20]:
            lines.append(f"  • {title}")
        if len(titles) > 20:
            lines.append(f"  <i>...and {len(titles) - 20} more</i>")

        self._send("\n".join(lines))
