"""
Persistent cleanup state for Ferret.
Tracks when items were first flagged so we can enforce a countdown
before deletion and survive container restarts.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from loguru import logger


CLEANUP_STATE_FILE = "/app/data/cleanup_state.json"


class CleanupState:
    """
    JSON-backed store mapping title keys to their first-flagged date.
    Schema: { "title (lower)": {"first_flagged": "2026-04-04", "rule": "Stale Shows"} }
    """

    def __init__(self, path: str | None = None):
        self.path = path or CLEANUP_STATE_FILE
        self.state: dict[str, dict] = self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, dict]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
            logger.info(f"CLEANUP STATE: Loaded {len(data)} tracked items from {self.path}")
            return data
        except Exception as e:
            logger.error(f"CLEANUP STATE: Failed to load {self.path}: {e}")
            return {}

    def _save(self) -> None:
        try:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w") as f:
                json.dump(self.state, f, indent=2, sort_keys=True)
            logger.debug(f"CLEANUP STATE: Saved {len(self.state)} tracked items")
        except Exception as e:
            logger.error(f"CLEANUP STATE: Failed to save {self.path}: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, current_flagged: list) -> None:
        """
        Reconcile state with the latest scan results.
        - Items no longer flagged are removed (someone watched them, etc.).
        - Newly flagged items get today's date recorded.
        """
        current_keys = {item.title.lower() for item in current_flagged}

        # Remove items that dropped off (preserve the "exclusions" sub-dict)
        removed = [k for k in self.state if k not in current_keys and k != "exclusions"]
        for k in removed:
            logger.info(f"CLEANUP STATE: '{k}' no longer flagged -- removing from countdown")
            del self.state[k]

        # Add new items with today's date
        for item in current_flagged:
            key = item.title.lower()
            if key not in self.state:
                self.state[key] = {
                    "first_flagged": datetime.now().isoformat()[:10],
                    "rule": item.rule_name,
                }
                logger.info(f"CLEANUP STATE: '{item.title}' newly flagged under '{item.rule_name}'")

        self._save()

    def _is_tracked_item(self, key: str) -> bool:
        """Check if a key is a tracked flagged item (not metadata like 'exclusions')."""
        return key != "exclusions" and isinstance(self.state.get(key), dict) and "first_flagged" in self.state.get(key, {})

    def days_until_deletion(self, title: str, delete_after_days: int = 30) -> int:
        """How many days remain before this item is eligible for auto-deletion."""
        key = title.lower()
        if self._is_tracked_item(key):
            first = datetime.fromisoformat(self.state[key]["first_flagged"])
            elapsed = (datetime.now() - first).days
            return max(0, delete_after_days - elapsed)
        return delete_after_days

    def days_flagged(self, title: str) -> int:
        """How many days this item has been continuously flagged."""
        key = title.lower()
        if self._is_tracked_item(key):
            first = datetime.fromisoformat(self.state[key]["first_flagged"])
            return (datetime.now() - first).days
        return 0

    def items_ready_for_deletion(self, delete_after_days: int = 30) -> list[str]:
        """Return title keys that have been flagged for >= delete_after_days."""
        ready = []
        now = datetime.now()
        for key, info in self.state.items():
            if not self._is_tracked_item(key):
                continue
            first = datetime.fromisoformat(info["first_flagged"])
            if (now - first).days >= delete_after_days:
                ready.append(key)
        return ready

    def add_exclusion(self, title: str) -> bool:
        """
        Remove a title from the countdown tracking and add it to the
        persistent exclusion list (survives container restarts).
        Returns True if the title was added to exclusions.
        """
        key = title.lower()
        # Remove from countdown tracking
        if key in self.state:
            del self.state[key]

        # Add to persistent exclusion list
        if "exclusions" not in self.state:
            self.state["exclusions"] = {}
        if key not in self.state.get("exclusions", {}):
            self.state["exclusions"][key] = {
                "excluded_at": datetime.now().isoformat()[:10],
                "title_original": title,
            }

        self._save()
        logger.info(f"CLEANUP STATE: '{title}' excluded -- removed from countdown, added to persistent exclusions")
        return True

    def get_exclusions(self) -> set[str]:
        """Return the set of persistently excluded title keys (lowercase)."""
        return set(self.state.get("exclusions", {}).keys())

    def remove_exclusion(self, title: str) -> bool:
        """Remove a title from the persistent exclusion list."""
        key = title.lower()
        exclusions = self.state.get("exclusions", {})
        if key in exclusions:
            del exclusions[key]
            self._save()
            return True
        return False

    def get_all(self) -> dict[str, dict]:
        """Return a copy of the full state dict (excluding the exclusions sub-dict)."""
        return {k: v for k, v in self.state.items() if k != "exclusions"}
