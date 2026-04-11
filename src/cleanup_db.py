"""
SQLite-backed cleanup state management for Ferret.

Replaces cleanup_state.json with a proper database that:
- Tracks every library item the engine has ever seen (prevents first-run notification floods)
- Persists flagged items with their rule, first_flagged date, and countdown
- Stores exclusions durably (survives container restarts and state resets)
- Keeps an audit log of deletions
- Records scan history for trend visibility

The public API is a superset of the old CleanupState class so the
migration path is: replace `CleanupState(path)` with `CleanupDB(path)`.
"""

import sqlite3
import json
import os
from datetime import datetime, date, timedelta
from loguru import logger


_SCHEMA = """
-- Items the engine has seen across ANY scan. Seeded on first run so
-- that items already in the library don't trigger "newly flagged"
-- notifications. The title_key is always lowercase for consistent
-- lookups; title_display preserves the original casing for the UI.
CREATE TABLE IF NOT EXISTS library_items (
    title_key    TEXT PRIMARY KEY,
    title_display TEXT NOT NULL,
    media_type   TEXT,            -- 'show' or 'movie'
    first_seen   DATE NOT NULL DEFAULT (DATE('now'))
);

-- Items currently matching a cleanup rule. Rows are upserted on each
-- scan (new items get today's date; existing items keep their original
-- first_flagged). Items that stop matching are deleted so the table
-- always reflects the latest scan.
CREATE TABLE IF NOT EXISTS flagged_items (
    title_key     TEXT PRIMARY KEY,
    title_display TEXT NOT NULL,
    media_type    TEXT,
    rule_name     TEXT NOT NULL,
    first_flagged DATE NOT NULL DEFAULT (DATE('now')),
    FOREIGN KEY (title_key) REFERENCES library_items(title_key)
);

-- Titles the user explicitly excluded from cleanup. Exclusions are
-- permanent until the user removes them. The exclude set is loaded on
-- engine startup and merged into the in-memory exclude list.
CREATE TABLE IF NOT EXISTS exclusions (
    title_key      TEXT PRIMARY KEY,
    title_display  TEXT NOT NULL,
    excluded_at    DATETIME NOT NULL DEFAULT (DATETIME('now'))
);

-- Audit trail of items the engine actually deleted from Sonarr/Radarr.
-- Once deleted, there's no other record — this is the only place that
-- remembers "we had Batman Begins and removed it on 2026-05-01."
CREATE TABLE IF NOT EXISTS deleted_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    media_type    TEXT,
    rule_name     TEXT,
    requested_by  TEXT,            -- Seerr username who originally requested it
    deleted_at    DATETIME NOT NULL DEFAULT (DATETIME('now'))
);

-- One row per cleanup scan. Useful for dashboards and debugging.
CREATE TABLE IF NOT EXISTS scans (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at     DATETIME NOT NULL DEFAULT (DATETIME('now')),
    items_scanned  INTEGER NOT NULL DEFAULT 0,
    flagged_count  INTEGER NOT NULL DEFAULT 0,
    deleted_count  INTEGER NOT NULL DEFAULT 0
);
"""


class CleanupDB:
    """
    Drop-in replacement for CleanupState backed by SQLite.

    Usage:
        db = CleanupDB("/app/data/cleanup.db")
        db.update(flagged_items)
        ready = db.items_ready_for_deletion(30)
    """

    def __init__(self, path: str | None = None):
        self.path = path or "/app/data/cleanup.db"
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

        self._try_migrate_json()

    # ------------------------------------------------------------------
    # Migration from cleanup_state.json
    # ------------------------------------------------------------------

    def _try_migrate_json(self):
        """One-shot import of the old JSON state file into the DB.

        Runs on first startup if the JSON file exists AND the DB's
        flagged_items table is empty. After import the JSON file is
        renamed to .migrated so it doesn't re-import on every restart.
        """
        json_path = os.path.join(os.path.dirname(self.path), "cleanup_state.json")
        if not os.path.exists(json_path):
            return

        # Only migrate if the DB is fresh
        row = self._conn.execute("SELECT COUNT(*) FROM flagged_items").fetchone()
        if row[0] > 0:
            return

        try:
            with open(json_path) as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"CLEANUP_DB: Could not read {json_path} for migration: {e}")
            return

        exclusions = data.pop("exclusions", {})
        migrated_flagged = 0
        migrated_exclusions = 0

        for title_key, info in data.items():
            if not isinstance(info, dict) or "first_flagged" not in info:
                continue
            first_flagged = info.get("first_flagged", date.today().isoformat())
            rule = info.get("rule", "Unknown")
            self._conn.execute(
                """INSERT OR IGNORE INTO library_items (title_key, title_display, first_seen)
                   VALUES (?, ?, ?)""",
                (title_key, title_key, first_flagged),
            )
            self._conn.execute(
                """INSERT OR IGNORE INTO flagged_items
                   (title_key, title_display, rule_name, first_flagged)
                   VALUES (?, ?, ?, ?)""",
                (title_key, title_key, rule, first_flagged),
            )
            migrated_flagged += 1

        for title_key, exc_info in exclusions.items():
            display = exc_info.get("title_original", title_key) if isinstance(exc_info, dict) else title_key
            excluded_at = exc_info.get("excluded_at", datetime.now().isoformat()) if isinstance(exc_info, dict) else datetime.now().isoformat()
            self._conn.execute(
                """INSERT OR IGNORE INTO exclusions (title_key, title_display, excluded_at)
                   VALUES (?, ?, ?)""",
                (title_key, display, excluded_at),
            )
            migrated_exclusions += 1

        self._conn.commit()

        # Rename so we don't re-import
        migrated_path = json_path + ".migrated"
        try:
            os.rename(json_path, migrated_path)
        except OSError:
            pass

        logger.info(
            f"CLEANUP_DB: Migrated {migrated_flagged} flagged items and "
            f"{migrated_exclusions} exclusions from JSON → SQLite"
        )

    # ------------------------------------------------------------------
    # Core API (matches old CleanupState interface)
    # ------------------------------------------------------------------

    def update(self, current_flagged: list) -> list[str]:
        """Reconcile the DB with the latest scan results.

        - Items in current_flagged that aren't in the DB get inserted
          with today's date (and are returned as "newly flagged").
        - Items in current_flagged that ARE already in the DB keep their
          original first_flagged date (upsert preserves it).
        - Items in the DB that are NOT in current_flagged get removed
          (they no longer match any rule).

        Also ensures every flagged item has a library_items row.

        Returns: list of title_keys that are genuinely new (never seen
        in flagged_items before — not even in a prior scan session).
        """
        current_keys = set()
        newly_flagged = []

        for item in current_flagged:
            title_key = item.title.lower()
            current_keys.add(title_key)

            # Ensure library_items row exists
            self._conn.execute(
                """INSERT OR IGNORE INTO library_items
                   (title_key, title_display, media_type)
                   VALUES (?, ?, ?)""",
                (title_key, item.title, item.media_type),
            )

            # Check if this is genuinely new (never been in flagged_items)
            existing = self._conn.execute(
                "SELECT first_flagged FROM flagged_items WHERE title_key = ?",
                (title_key,),
            ).fetchone()

            if existing is None:
                # Brand new — insert with today's date
                self._conn.execute(
                    """INSERT INTO flagged_items
                       (title_key, title_display, media_type, rule_name, first_flagged)
                       VALUES (?, ?, ?, ?, DATE('now'))""",
                    (title_key, item.title, item.media_type, item.rule_name),
                )
                newly_flagged.append(title_key)
            else:
                # Already tracked — update rule_name/display but keep first_flagged
                self._conn.execute(
                    """UPDATE flagged_items
                       SET title_display = ?, media_type = ?, rule_name = ?
                       WHERE title_key = ?""",
                    (item.title, item.media_type, item.rule_name, title_key),
                )

        # Remove items no longer flagged
        if current_keys:
            placeholders = ",".join("?" for _ in current_keys)
            self._conn.execute(
                f"DELETE FROM flagged_items WHERE title_key NOT IN ({placeholders})",
                list(current_keys),
            )
        else:
            self._conn.execute("DELETE FROM flagged_items")

        self._conn.commit()
        return newly_flagged

    def get_all(self) -> dict[str, dict]:
        """Return all currently flagged items as a dict (backwards compat).

        Returns {title_key: {"first_flagged": "YYYY-MM-DD", "rule": "..."}}
        """
        rows = self._conn.execute(
            "SELECT title_key, first_flagged, rule_name FROM flagged_items"
        ).fetchall()
        return {
            row["title_key"]: {
                "first_flagged": row["first_flagged"],
                "rule": row["rule_name"],
            }
            for row in rows
        }

    def days_until_deletion(self, title: str, delete_after_days: int = 30) -> int:
        """Days remaining before an item is eligible for deletion."""
        row = self._conn.execute(
            "SELECT first_flagged FROM flagged_items WHERE title_key = ?",
            (title.lower(),),
        ).fetchone()
        if not row:
            return delete_after_days

        first_flagged = date.fromisoformat(row["first_flagged"])
        elapsed = (date.today() - first_flagged).days
        return max(0, delete_after_days - elapsed)

    def days_flagged(self, title: str) -> int:
        """Days since an item was first flagged."""
        row = self._conn.execute(
            "SELECT first_flagged FROM flagged_items WHERE title_key = ?",
            (title.lower(),),
        ).fetchone()
        if not row:
            return 0
        first_flagged = date.fromisoformat(row["first_flagged"])
        return (date.today() - first_flagged).days

    def items_ready_for_deletion(self, delete_after_days: int = 30) -> list[str]:
        """Return title_keys of items flagged for >= delete_after_days."""
        cutoff = (date.today() - timedelta(days=delete_after_days)).isoformat()
        rows = self._conn.execute(
            "SELECT title_key FROM flagged_items WHERE first_flagged <= ?",
            (cutoff,),
        ).fetchall()
        return [row["title_key"] for row in rows]

    # ------------------------------------------------------------------
    # Exclusions
    # ------------------------------------------------------------------

    def add_exclusion(self, title: str) -> bool:
        """Exclude a title from cleanup. Removes it from flagged_items too."""
        title_key = title.lower()
        try:
            self._conn.execute(
                """INSERT OR REPLACE INTO exclusions
                   (title_key, title_display) VALUES (?, ?)""",
                (title_key, title),
            )
            self._conn.execute(
                "DELETE FROM flagged_items WHERE title_key = ?", (title_key,)
            )
            self._conn.commit()
            return True
        except Exception as e:
            logger.error(f"CLEANUP_DB: Failed to add exclusion '{title}': {e}")
            return False

    def remove_exclusion(self, title: str) -> bool:
        """Remove a title from the exclusion list."""
        title_key = title.lower()
        cursor = self._conn.execute(
            "DELETE FROM exclusions WHERE title_key = ?", (title_key,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_exclusions(self) -> set[str]:
        """Return all excluded title_keys."""
        rows = self._conn.execute("SELECT title_key FROM exclusions").fetchall()
        return {row["title_key"] for row in rows}

    # ------------------------------------------------------------------
    # Audit + history (new — not in old CleanupState)
    # ------------------------------------------------------------------

    def record_deletions(self, items: list[dict]) -> None:
        """Log deleted items to the audit trail.

        Each item dict should have: title, media_type, rule_name,
        and optionally requested_by (Seerr username).
        """
        for item in items:
            self._conn.execute(
                """INSERT INTO deleted_items
                   (title, media_type, rule_name, requested_by)
                   VALUES (?, ?, ?, ?)""",
                (
                    item.get("title", "Unknown"),
                    item.get("media_type"),
                    item.get("rule_name"),
                    item.get("requested_by"),
                ),
            )
            # Also remove from flagged_items
            self._conn.execute(
                "DELETE FROM flagged_items WHERE title_key = ?",
                (item.get("title", "").lower(),),
            )
        self._conn.commit()

    def record_scan(self, items_scanned: int, flagged_count: int, deleted_count: int = 0) -> None:
        """Record a scan in the history table."""
        self._conn.execute(
            """INSERT INTO scans (items_scanned, flagged_count, deleted_count)
               VALUES (?, ?, ?)""",
            (items_scanned, flagged_count, deleted_count),
        )
        self._conn.commit()

    def seed_library_items(self, items: list[dict]) -> int:
        """Seed library_items from the current library scan.

        Call this after fetching the full library from Plex/Jellyfin/Emby
        so items already in the library are marked as "known." Any item
        already in the table is left untouched (INSERT OR IGNORE).

        Each dict should have: title, media_type.
        Returns the number of new items seeded.
        """
        count = 0
        for item in items:
            title_key = item.get("title", "").lower()
            if not title_key:
                continue
            cursor = self._conn.execute(
                """INSERT OR IGNORE INTO library_items
                   (title_key, title_display, media_type)
                   VALUES (?, ?, ?)""",
                (title_key, item.get("title", ""), item.get("media_type")),
            )
            count += cursor.rowcount
        self._conn.commit()
        return count

    def get_deletion_history(self, limit: int = 50) -> list[dict]:
        """Return recent deletion audit entries."""
        rows = self._conn.execute(
            """SELECT title, media_type, rule_name, requested_by, deleted_at
               FROM deleted_items ORDER BY deleted_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_scan_history(self, limit: int = 30) -> list[dict]:
        """Return recent scan records."""
        rows = self._conn.execute(
            """SELECT scanned_at, items_scanned, flagged_count, deleted_count
               FROM scans ORDER BY scanned_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self):
        """Close the database connection."""
        self._conn.close()
