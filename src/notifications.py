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
        """Notify about newly flagged items.

        Previous version said "X new items flagged for cleanup" and ended with
        "30 days until deletion" which was alarming and misleading — a catalog
        item that's been in the library for 12 years is not "new", and telling
        the user it'll be deleted in 30 days when they haven't even reviewed it
        is the wrong tone.

        New version:
        - Says "match cleanup rules" not "flagged for cleanup"
        - Groups by rule name so the user knows WHY each item appeared
        - Ends with "Review on the Ferret dashboard" instead of a deletion threat
        - If the batch is huge (>30), shows a summary count per rule instead
          of a long item list that Telegram truncates anyway
        """
        if not self.enabled or not items:
            return

        count = len(items)

        # Group by rule
        by_rule: dict[str, list[dict]] = {}
        for item in items:
            rule = item.get("rule", "Unknown rule")
            by_rule.setdefault(rule, []).append(item)

        # For large batches, just summarise per rule — a 200-item list
        # is unreadable in a Telegram message anyway.
        if count > 30:
            lines = [f"<b>📋 {count} items match cleanup rules</b>"]
            lines.append("")
            for rule, rule_items in sorted(by_rule.items()):
                shows = sum(1 for i in rule_items if i.get("media_type") == "show")
                movies = sum(1 for i in rule_items if i.get("media_type") == "movie")
                parts = []
                if shows:
                    parts.append(f"{shows} show{'s' if shows != 1 else ''}")
                if movies:
                    parts.append(f"{movies} movie{'s' if movies != 1 else ''}")
                lines.append(f"  <b>{rule}</b> — {', '.join(parts)}")
            lines.append("")
            lines.append("Review on the Ferret dashboard to exclude or confirm.")
            self._send("\n".join(lines))
            return

        # For smaller batches, list items grouped by rule
        lines = [f"<b>📋 {count} item{'s' if count != 1 else ''} match cleanup rules</b>"]
        lines.append("")

        for rule, rule_items in sorted(by_rule.items()):
            lines.append(f"<b>{rule} ({len(rule_items)})</b>")
            for item in rule_items[:10]:
                reason = item.get("reason", "")
                lines.append(f"  • {item['title']}" + (f" — <i>{reason}</i>" if reason else ""))
            if len(rule_items) > 10:
                lines.append(f"  <i>...and {len(rule_items) - 10} more</i>")
            lines.append("")

        lines.append("Review on the Ferret dashboard to exclude or confirm.")

        self._send("\n".join(lines))

    def notify_deletion_warning(self, items: list[dict]) -> None:
        """Notify about items 7 days or less from deletion."""
        if not self.enabled or not items:
            return

        count = len(items)
        lines = [f"<b>⚠️ {count} item{'s' if count != 1 else ''} scheduled for deletion within 7 days</b>"]
        lines.append("")

        for item in items[:15]:
            days = item.get("days_until_deletion", "?")
            lines.append(f"  • {item['title']} — <b>{days}d remaining</b>")
        if len(items) > 15:
            lines.append(f"  <i>...and {len(items) - 15} more</i>")

        lines.append("")
        lines.append("Exclude from the Ferret dashboard to prevent deletion.")

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
