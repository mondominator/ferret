import sqlite3
from datetime import datetime
from pathlib import Path
from loguru import logger

from plexapi.video import Movie, Episode


class TautulliLogger:
    """
    Writes playback history directly to Tautulli's database.
    This allows Ferret syncs to appear in Tautulli history.
    """

    def __init__(self, database_path: str | None = None, test_mode: bool = False):
        """
        Initialize Tautulli logger.

        Args:
            database_path: Path to Tautulli's tautulli.db file (or "test" for test mode)
            test_mode: If True, only logs what would be written without accessing database
        """
        self.database_path = database_path
        self.test_mode = test_mode or database_path == "test"
        self.backfilled_users = set()  # Track which users have been backfilled this session

        self._conn = None

        if self.test_mode:
            self.enabled = True
            logger.info("Tautulli: TEST MODE - Will log intended writes without database access")
        else:
            self.enabled = database_path is not None and Path(database_path).exists()

            if database_path and not self.enabled:
                logger.warning(
                    f"Tautulli: Database not found at {database_path}, history logging disabled"
                )
            elif self.enabled:
                logger.info(f"Tautulli: History logging enabled to {database_path}")
                # Open a persistent connection with WAL mode to avoid locking issues
                self._conn = sqlite3.connect(self.database_path, timeout=30)
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA busy_timeout=5000")

    def entry_exists(
        self,
        rating_key: int,
        user_id: str,
    ) -> bool:
        """
        Check if a watch entry already exists in Tautulli for this item and user.

        Args:
            rating_key: Plex rating key for the item
            user_id: Plex user ID

        Returns:
            True if entry exists, False otherwise
        """
        if not self.enabled or self.test_mode:
            return False

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT COUNT(*) FROM session_history
                WHERE rating_key = ? AND user_id = ?
                """,
                (rating_key, user_id),
            )

            count = cursor.fetchone()[0]
            return count > 0

        except sqlite3.Error as e:
            logger.warning(f"Tautulli: Error checking if entry exists: {e}")
            return False

    def log_watch(
        self,
        item: Movie | Episode,
        user_name: str,
        user_id: str,
        server_name: str,
        machine_id: str,
        watch_time: int | None = None,
        section_id: int | None = None,
        watch_timestamp: int | None = None,
    ) -> None:
        """
        Log a watch event to Tautulli's database.

        Args:
            item: The Movie or Episode that was watched
            user_name: Plex username
            user_id: Plex user ID
            server_name: Plex server name
            machine_id: Plex server machine identifier
            watch_time: Watch duration in milliseconds (None = fully watched)
            section_id: Plex library section ID
            watch_timestamp: Unix timestamp when item was watched (None = now)
        """
        if not self.enabled:
            return

        duration = item.duration or 0
        watched_duration = watch_time if watch_time is not None else duration

        # Calculate percentage watched
        percent_complete = (
            min(100, int((watched_duration / duration) * 100)) if duration > 0 else 0
        )

        # Determine media type
        media_type = "movie" if hasattr(item, "year") and not hasattr(item, "grandparentTitle") else "episode"

        # Get the item's GUID
        item_guid = getattr(item, "guid", None)

        # Build full_title
        if media_type == "episode":
            full_title = f"{getattr(item, 'grandparentTitle', '')} - {item.title}"
        else:
            full_title = item.title

        try:
            # Build session data
            # Use provided timestamp or current time
            stopped_timestamp = watch_timestamp if watch_timestamp is not None else int(datetime.now().timestamp())
            session_data = {
                "started": stopped_timestamp - int(watched_duration / 1000),  # Backdate start time
                "stopped": stopped_timestamp,
                "user": user_name,
                "user_id": user_id,
                "rating_key": item.ratingKey,
                "parent_rating_key": getattr(item, "parentRatingKey", ""),
                "grandparent_rating_key": getattr(item, "grandparentRatingKey", ""),
                "title": item.title,
                "parent_title": getattr(item, "parentTitle", ""),
                "grandparent_title": getattr(item, "grandparentTitle", ""),
                "full_title": full_title,
                "guid": item_guid,
                "media_type": media_type,
                "year": getattr(item, "year", ""),
                "duration": duration,
                "watched_duration": watched_duration,
                "percent_complete": percent_complete,
                "watched_status": 1 if percent_complete >= 90 else 0,
                "server": server_name,
                "machine_id": machine_id,
                "player": "ferret",
                "section_id": section_id,
            }

            logger.debug(f"Tautulli: session_data section_id = {session_data.get('section_id')}")

            if self.test_mode:
                # Test mode: just log what would be written
                logger.info(
                    f"Tautulli: [TEST MODE] Would log watch: "
                    f"{item.title} by {user_name} ({percent_complete}% watched, "
                    f"{media_type}, duration={duration}ms, server={server_name})"
                )
            else:
                # Real mode: Insert into Tautulli database
                self._insert_session(session_data)
                logger.info(
                    f"Tautulli: Logged watch for {item.title} by {user_name} ({percent_complete}% watched)"
                )

        except Exception as e:
            logger.warning(f"Tautulli: Failed to log watch for {item.title}: {e}")

    def _get_connection(self) -> sqlite3.Connection:
        """Return the persistent DB connection, reconnecting if needed."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.database_path, timeout=30)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    def _insert_session(self, session_data: dict) -> None:
        """
        Insert a session into Tautulli's session_history table.

        Args:
            session_data: Dictionary containing session information
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Insert into session_history table with reference_id = id for proper linking
            # Note: Tautulli schema doesn't have watched_status/percent_complete in session_history
            cursor.execute(
                """
                INSERT INTO session_history (
                    reference_id, started, stopped, rating_key, parent_rating_key, grandparent_rating_key,
                    media_type, user_id, user, ip_address, paused_counter, player,
                    product, platform, machine_id, location, view_offset, section_id
                ) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_data["started"],
                    session_data["stopped"],
                    session_data["rating_key"],
                    session_data.get("parent_rating_key", ""),
                    session_data.get("grandparent_rating_key", ""),
                    session_data["media_type"],
                    session_data["user_id"],
                    session_data["user"],
                    "sync",  # ip_address - mark as sync
                    0,  # paused_counter
                    session_data["player"],
                    "Ferret",  # product
                    "Ferret",  # platform
                    session_data["machine_id"],
                    "lan",  # location
                    session_data["watched_duration"],  # view_offset
                    session_data.get("section_id"),  # section_id
                ),
            )

            session_history_id = cursor.lastrowid

            # Update reference_id to match the id for proper session linking
            cursor.execute(
                "UPDATE session_history SET reference_id = ? WHERE id = ?",
                (session_history_id, session_history_id),
            )

            # Insert into session_history_metadata table for additional details
            # Use current timestamp for added_at, updated_at, and last_viewed_at
            now_timestamp = session_data["stopped"]

            cursor.execute(
                """
                INSERT INTO session_history_metadata (
                    id, rating_key, parent_rating_key, grandparent_rating_key,
                    title, parent_title, grandparent_title, full_title, media_type, year, duration,
                    guid, added_at, updated_at, last_viewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_history_id,
                    session_data["rating_key"],
                    session_data.get("parent_rating_key", ""),
                    session_data.get("grandparent_rating_key", ""),
                    session_data["title"],
                    session_data.get("parent_title", ""),
                    session_data.get("grandparent_title", ""),
                    session_data.get("full_title", ""),
                    session_data["media_type"],
                    session_data.get("year", ""),
                    session_data["duration"],
                    session_data.get("guid"),
                    now_timestamp,  # added_at
                    now_timestamp,  # updated_at
                    now_timestamp,  # last_viewed_at - critical for Maintainerr
                ),
            )

            # Insert into session_history_media_info table
            # This is required for Tautulli/Maintainerr to recognize the session
            cursor.execute(
                """
                INSERT INTO session_history_media_info (
                    id, rating_key, video_decision, audio_decision, transcode_decision, duration
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_history_id,
                    session_data["rating_key"],
                    "direct play",  # video_decision
                    "direct play",  # audio_decision
                    "direct play",  # transcode_decision
                    session_data["duration"],
                ),
            )

            conn.commit()

        except sqlite3.Error as e:
            logger.warning(f"Tautulli: Database error: {e}")
            try:
                conn.rollback()
            except Exception:
                pass

    def backfill_user_watched(
        self,
        user,
        user_plex,
        libraries,
        server_name: str,
        machine_id: str,
    ) -> int:
        """
        Backfill Tautulli history for all watched items that don't have entries yet.
        Only runs once per user per session.

        Args:
            user: Plex user object
            user_plex: PlexServer instance for this user
            libraries: List of library sections to backfill
            server_name: Plex server name
            machine_id: Plex server machine identifier
        """
        if not self.enabled:
            return 0

        # Check if we've already backfilled this user this session
        user_id = user.id if hasattr(user, 'id') else user.title
        if user_id in self.backfilled_users:
            logger.debug(f"Tautulli: Skipping backfill for {user.title} - already done this session")
            return 0

        self.backfilled_users.add(user_id)
        logger.debug(f"Tautulli: Starting backfill for user {user.title}")

        backfill_count = 0

        for library in libraries:
            try:
                logger.debug(f"Tautulli: Backfilling library {library.title} for {user.title}")

                # Get section_id
                section_id = None
                if hasattr(library, 'key') and library.key is not None:
                    try:
                        if isinstance(library.key, int):
                            section_id = library.key
                        else:
                            section_id = int(str(library.key).split('/')[-1])
                    except (ValueError, IndexError, AttributeError) as e:
                        logger.warning(f"Could not extract section_id from {library.key}: {e}")

                library_section = user_plex.library.section(library.title)

                if library.type == "movie":
                    # Get all watched movies
                    for movie in library_section.search(unwatched=False):
                        if not movie.isWatched:
                            continue

                        # Check if entry already exists
                        if self.entry_exists(movie.ratingKey, user.id):
                            logger.debug(f"Tautulli: Skipping {movie.title} - already in history")
                            continue

                        # Determine timestamp to use
                        watch_timestamp = None
                        if hasattr(movie, 'lastViewedAt') and movie.lastViewedAt:
                            watch_timestamp = int(movie.lastViewedAt.timestamp())
                            logger.debug(f"Tautulli: Using lastViewedAt for {movie.title}")
                        elif hasattr(movie, 'addedAt') and movie.addedAt:
                            watch_timestamp = int(movie.addedAt.timestamp())
                            logger.debug(f"Tautulli: Using addedAt for {movie.title}")

                        # Log the watch
                        self.log_watch(
                            item=movie,
                            user_name=user.title,
                            user_id=user.id,
                            server_name=server_name,
                            machine_id=machine_id,
                            watch_time=None,
                            section_id=section_id,
                            watch_timestamp=watch_timestamp,
                        )
                        backfill_count += 1

                elif library.type == "show":
                    # Get all shows and their watched episodes
                    for show in library_section.search(unwatched=False):
                        for episode in show.watched():
                            # Check if entry already exists
                            if self.entry_exists(episode.ratingKey, user.id):
                                logger.debug(f"Tautulli: Skipping {show.title} {episode.title} - already in history")
                                continue

                            # Determine timestamp to use
                            watch_timestamp = None
                            if hasattr(episode, 'lastViewedAt') and episode.lastViewedAt:
                                watch_timestamp = int(episode.lastViewedAt.timestamp())
                                logger.debug(f"Tautulli: Using lastViewedAt for {show.title} {episode.title}")
                            elif hasattr(episode, 'addedAt') and episode.addedAt:
                                watch_timestamp = int(episode.addedAt.timestamp())
                                logger.debug(f"Tautulli: Using addedAt for {show.title} {episode.title}")

                            # Log the watch
                            self.log_watch(
                                item=episode,
                                user_name=user.title,
                                user_id=user.id,
                                server_name=server_name,
                                machine_id=machine_id,
                                watch_time=None,
                                section_id=section_id,
                                watch_timestamp=watch_timestamp,
                            )
                            backfill_count += 1

            except Exception as e:
                logger.error(f"Tautulli: Failed to backfill library {library.title}: {e}")

        if backfill_count > 0:
            logger.info(f"Tautulli: Backfill complete for {user.title} - added {backfill_count} entries")
        else:
            logger.debug(f"Tautulli: Backfill complete for {user.title} - no new entries")
        return backfill_count
