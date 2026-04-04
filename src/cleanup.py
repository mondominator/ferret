"""
Media lifecycle cleanup engine for Ferret.
Checks watch history across ALL connected servers (Plex, Jellyfin, Emby)
and flags stale content for deletion.

ALL ACTIONS ARE DRY RUN ONLY. No actual deletion is performed.
"""

from datetime import datetime, timezone
from dataclasses import dataclass, field
from loguru import logger

from src.plex import Plex
from src.jellyfin import Jellyfin
from src.emby import Emby
from src.jellyfin_emby import JellyfinEmby
from src.functions import str_to_bool, get_env_value


@dataclass
class CleanupRule:
    name: str
    media_type: str  # "show" or "movie"
    max_age_days: int  # days since last watch
    exclude_continuing: bool = True  # skip ongoing shows
    min_watched: int | None = None  # None = any watch counts, 0 = never watched


@dataclass
class FlaggedItem:
    title: str
    media_type: str  # "show" or "movie"
    last_watched_date: datetime | None  # None if never watched on any server
    last_watched_server: str | None  # server name where it was most recently watched
    days_since_watched: int | None  # None if never watched
    rule_name: str
    servers_checked: list[str] = field(default_factory=list)
    library_name: str = ""


@dataclass
class CleanupResults:
    flagged_items: list[FlaggedItem] = field(default_factory=list)
    total_scanned: int = 0
    scan_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    dry_run: bool = True

    @property
    def flagged_count(self) -> int:
        return len(self.flagged_items)

    @property
    def flagged_shows(self) -> list[FlaggedItem]:
        return [i for i in self.flagged_items if i.media_type == "show"]

    @property
    def flagged_movies(self) -> list[FlaggedItem]:
        return [i for i in self.flagged_items if i.media_type == "movie"]

    def to_dict(self) -> dict:
        return {
            "flagged_count": self.flagged_count,
            "flagged_shows_count": len(self.flagged_shows),
            "flagged_movies_count": len(self.flagged_movies),
            "total_scanned": self.total_scanned,
            "scan_time": self.scan_time.isoformat(),
            "dry_run": self.dry_run,
            "flagged_items": [
                {
                    "title": item.title,
                    "media_type": item.media_type,
                    "last_watched_date": item.last_watched_date.strftime("%Y-%m-%d") if item.last_watched_date else "Never",
                    "last_watched_server": item.last_watched_server or "N/A",
                    "days_since_watched": item.days_since_watched,
                    "rule_name": item.rule_name,
                    "servers_checked": item.servers_checked,
                    "library_name": item.library_name,
                }
                for item in self.flagged_items
            ],
        }


class CleanupEngine:
    def __init__(self, servers: list, env, dry_run: bool = True):
        self.servers = servers
        self.env = env
        # Always force dry_run to True for safety
        self.dry_run = True
        if not dry_run:
            logger.warning("CLEANUP: dry_run=False was requested but is NOT supported yet. Forcing dry_run=True.")

        # Parse exclusion list — comma-separated titles or patterns (case-insensitive)
        # Supports wildcards: "Star*" matches anything starting with "Star"
        # Supports exact matches: "Batman: The Animated Series"
        exclude_str = get_env_value(env, "CLEANUP_EXCLUDE_TITLES", "")
        self.exclude_exact = set()
        self.exclude_prefixes = []
        if exclude_str:
            for entry in exclude_str.split(","):
                entry = entry.strip()
                if not entry:
                    continue
                if entry.endswith("*"):
                    self.exclude_prefixes.append(entry[:-1].lower())
                else:
                    self.exclude_exact.add(entry.lower())
            total = len(self.exclude_exact) + len(self.exclude_prefixes)
            logger.info(f"CLEANUP: {total} exclusion rules loaded")

    def _get_server_name(self, server) -> str:
        """Get a human-readable name for a server."""
        if isinstance(server, Plex):
            return f"Plex ({server.plex.friendlyName})"
        elif isinstance(server, JellyfinEmby):
            return f"{server.server_type} ({server.server_name})"
        return "Unknown"

    def _get_plex_library_media(self, server: Plex) -> dict[str, list[dict]]:
        """
        Get all media from a Plex server organized by library.
        Returns dict of library_name -> list of media items with watch info.
        """
        media = {}
        try:
            libraries = server.plex.library.sections()
            for library in libraries:
                if library.type not in ["movie", "show"]:
                    continue

                lib_items = []
                if library.type == "movie":
                    for movie in library.all():
                        last_viewed = None
                        if movie.lastViewedAt:
                            last_viewed = movie.lastViewedAt.replace(tzinfo=timezone.utc)
                        lib_items.append({
                            "title": movie.title,
                            "media_type": "movie",
                            "watched": movie.isWatched,
                            "last_viewed": last_viewed,
                        })
                elif library.type == "show":
                    for show in library.all():
                        # Find the most recent episode watch date for the show
                        most_recent_watch = None
                        any_watched = False
                        is_continuing = getattr(show, 'status', '') in ['Continuing', 'Returning Series']

                        for episode in show.episodes():
                            if episode.isWatched:
                                any_watched = True
                                if episode.lastViewedAt:
                                    ep_date = episode.lastViewedAt.replace(tzinfo=timezone.utc)
                                    if most_recent_watch is None or ep_date > most_recent_watch:
                                        most_recent_watch = ep_date

                        lib_items.append({
                            "title": show.title,
                            "media_type": "show",
                            "watched": any_watched,
                            "last_viewed": most_recent_watch,
                            "is_continuing": is_continuing,
                        })

                media[library.title] = lib_items
        except Exception as e:
            logger.error(f"CLEANUP: Failed to get media from Plex server {server.plex.friendlyName}: {e}")

        return media

    def _get_jellyfin_emby_library_media(self, server: JellyfinEmby) -> dict[str, list[dict]]:
        """
        Get all media from a Jellyfin/Emby server organized by library.
        Returns dict of library_name -> list of media items with watch info.
        """
        media = {}
        try:
            # Use the first user (admin) to scan libraries
            if not server.users:
                logger.warning(f"CLEANUP: No users found on {server.server_type} server {server.server_name}")
                return media

            user_name = list(server.users.keys())[0]
            user_id = server.users[user_name]

            all_libraries = server.query(f"/Users/{user_id}/Views", "get")
            if not all_libraries or not isinstance(all_libraries, dict):
                return media

            for library in all_libraries.get("Items", []):
                library_id = library.get("Id")
                library_title = library.get("Name")
                library_type = library.get("CollectionType")

                if library_type not in ["movies", "tvshows"]:
                    continue

                lib_items = []

                if library_type == "movies":
                    all_movies = server.query(
                        f"/Users/{user_id}/Items"
                        + f"?ParentId={library_id}&IncludeItemTypes=Movie&Recursive=True"
                        + "&Fields=ProviderIds,UserDataLastPlayedDate",
                        "get",
                    )
                    if all_movies and isinstance(all_movies, dict):
                        for movie in all_movies.get("Items", []):
                            user_data = movie.get("UserData", {})
                            last_played = user_data.get("LastPlayedDate")
                            last_viewed = None
                            if last_played:
                                try:
                                    last_viewed = datetime.fromisoformat(
                                        last_played.replace("Z", "+00:00")
                                    )
                                except (ValueError, TypeError):
                                    pass

                            lib_items.append({
                                "title": movie.get("Name", "Unknown"),
                                "media_type": "movie",
                                "watched": user_data.get("Played", False),
                                "last_viewed": last_viewed,
                            })

                elif library_type == "tvshows":
                    all_shows = server.query(
                        f"/Users/{user_id}/Items"
                        + f"?ParentId={library_id}&IncludeItemTypes=Series&Recursive=True"
                        + "&Fields=ProviderIds,Path,Status",
                        "get",
                    )
                    if all_shows and isinstance(all_shows, dict):
                        for show in all_shows.get("Items", []):
                            show_id = show.get("Id")
                            show_status = show.get("Status", "")
                            is_continuing = show_status in ["Continuing", "Returning Series"]

                            # Get episodes to find most recent watch date
                            most_recent_watch = None
                            any_watched = False

                            episodes = server.query(
                                f"/Shows/{show_id}/Episodes"
                                + f"?userId={user_id}&Fields=UserDataLastPlayedDate",
                                "get",
                            )
                            if episodes and isinstance(episodes, dict):
                                for ep in episodes.get("Items", []):
                                    ep_user_data = ep.get("UserData", {})
                                    if ep_user_data.get("Played"):
                                        any_watched = True
                                        ep_last_played = ep_user_data.get("LastPlayedDate")
                                        if ep_last_played:
                                            try:
                                                ep_date = datetime.fromisoformat(
                                                    ep_last_played.replace("Z", "+00:00")
                                                )
                                                if most_recent_watch is None or ep_date > most_recent_watch:
                                                    most_recent_watch = ep_date
                                            except (ValueError, TypeError):
                                                pass

                            lib_items.append({
                                "title": show.get("Name", "Unknown"),
                                "media_type": "show",
                                "watched": any_watched,
                                "last_viewed": most_recent_watch,
                                "is_continuing": is_continuing,
                            })

                media[library_title] = lib_items

        except Exception as e:
            logger.error(f"CLEANUP: Failed to get media from {server.server_type} server {server.server_name}: {e}")

        return media

    def _get_server_media(self, server) -> dict[str, list[dict]]:
        """Get all media from any server type."""
        if isinstance(server, Plex):
            return self._get_plex_library_media(server)
        elif isinstance(server, JellyfinEmby):
            return self._get_jellyfin_emby_library_media(server)
        return {}

    def _merge_watch_data_across_servers(
        self, all_server_media: list[tuple[str, dict[str, list[dict]]]]
    ) -> dict[str, dict]:
        """
        Merge watch data across all servers.
        For each unique title, find the MOST RECENT watch date across all servers.
        Returns a dict of title -> merged info.
        """
        merged: dict[str, dict] = {}

        for server_name, server_media in all_server_media:
            for library_name, items in server_media.items():
                for item in items:
                    title = item["title"]
                    media_type = item["media_type"]
                    key = f"{media_type}:{title}"

                    if key not in merged:
                        merged[key] = {
                            "title": title,
                            "media_type": media_type,
                            "last_viewed": None,
                            "last_viewed_server": None,
                            "watched_on_any": False,
                            "is_continuing": item.get("is_continuing", False),
                            "servers_checked": [],
                            "library_name": library_name,
                        }

                    existing = merged[key]
                    existing["servers_checked"].append(server_name)

                    # Track if watched on any server
                    if item["watched"]:
                        existing["watched_on_any"] = True

                    # Keep the most recent watch date across all servers
                    if item["last_viewed"]:
                        if existing["last_viewed"] is None or item["last_viewed"] > existing["last_viewed"]:
                            existing["last_viewed"] = item["last_viewed"]
                            existing["last_viewed_server"] = server_name

                    # Preserve continuing status from any server
                    if item.get("is_continuing"):
                        existing["is_continuing"] = True

        return merged

    def scan(self, rules: list[CleanupRule]) -> CleanupResults:
        """
        Scan all servers and return items that match cleanup rules.

        For each rule:
        1. Get all media from all connected servers
        2. For each item, check watched status across ALL servers
        3. Find the most recent watch date across all servers
        4. If no server has watched it within max_age_days, flag it
        """
        results = CleanupResults(dry_run=self.dry_run)
        now = datetime.now(timezone.utc)

        logger.info("CLEANUP: Starting media lifecycle scan across all servers")
        logger.info(f"CLEANUP: Dry run mode: {self.dry_run}")
        logger.info(f"CLEANUP: Rules: {[r.name for r in rules]}")

        # Step 1: Gather media from all servers
        all_server_media: list[tuple[str, dict[str, list[dict]]]] = []
        server_names = []

        for server in self.servers:
            server_name = self._get_server_name(server)
            server_names.append(server_name)
            logger.info(f"CLEANUP: Scanning {server_name}...")

            try:
                server_media = self._get_server_media(server)
                lib_count = sum(len(items) for items in server_media.values())
                logger.info(f"CLEANUP: Found {lib_count} items across {len(server_media)} libraries on {server_name}")
                all_server_media.append((server_name, server_media))
            except Exception as e:
                logger.error(f"CLEANUP: Failed to scan {server_name}: {e}")

        if not all_server_media:
            logger.warning("CLEANUP: No server data collected, skipping cleanup scan")
            return results

        # Step 2: Merge watch data across all servers
        merged = self._merge_watch_data_across_servers(all_server_media)
        results.total_scanned = len(merged)
        logger.info(f"CLEANUP: Merged {len(merged)} unique media items across {len(server_names)} servers")

        # Step 3: Apply rules
        for rule in rules:
            logger.info(f"CLEANUP: Applying rule '{rule.name}' (type={rule.media_type}, max_age={rule.max_age_days}d)")
            rule_flagged = 0

            for key, item_data in merged.items():
                # Filter by media type
                if item_data["media_type"] != rule.media_type:
                    continue

                # Skip excluded titles (favorites/protected)
                title_lower = item_data["title"].lower()
                if title_lower in self.exclude_exact or any(title_lower.startswith(p) for p in self.exclude_prefixes):
                    logger.debug(f"CLEANUP: Skipping '{item_data['title']}' -- in exclusion list")
                    continue

                # Skip continuing shows if configured
                if rule.exclude_continuing and item_data.get("is_continuing", False):
                    logger.debug(f"CLEANUP: Skipping '{item_data['title']}' -- continuing series")
                    continue

                # Check if min_watched applies (0 = only flag never-watched items)
                if rule.min_watched == 0 and item_data["watched_on_any"]:
                    continue

                # Calculate days since last watch
                last_viewed = item_data["last_viewed"]
                days_since = None

                if last_viewed:
                    # Ensure timezone-aware comparison
                    if last_viewed.tzinfo is None:
                        last_viewed = last_viewed.replace(tzinfo=timezone.utc)
                    delta = now - last_viewed
                    days_since = delta.days

                    # If watched within the threshold on ANY server, skip
                    if days_since < rule.max_age_days:
                        continue
                else:
                    # Never watched on any server -- this always exceeds max_age
                    pass

                # This item should be flagged
                flagged = FlaggedItem(
                    title=item_data["title"],
                    media_type=item_data["media_type"],
                    last_watched_date=last_viewed,
                    last_watched_server=item_data["last_viewed_server"],
                    days_since_watched=days_since,
                    rule_name=rule.name,
                    servers_checked=item_data["servers_checked"],
                    library_name=item_data["library_name"],
                )
                results.flagged_items.append(flagged)
                rule_flagged += 1

                # Log the flagged item
                if days_since is not None:
                    logger.info(
                        f"CLEANUP [DRY RUN]: Would flag '{item_data['title']}' "
                        f"-- not watched on any server in {days_since} days "
                        f"(threshold: {rule.max_age_days}d, last: {item_data['last_viewed_server']})"
                    )
                else:
                    logger.info(
                        f"CLEANUP [DRY RUN]: Would flag '{item_data['title']}' "
                        f"-- never watched on any server "
                        f"(threshold: {rule.max_age_days}d)"
                    )

            logger.info(f"CLEANUP: Rule '{rule.name}' flagged {rule_flagged} items")

        # Sort flagged items: never-watched first, then by days since watched (descending)
        results.flagged_items.sort(
            key=lambda x: (x.days_since_watched is not None, -(x.days_since_watched or 0))
        )

        logger.info(
            f"CLEANUP: Scan complete. "
            f"Scanned {results.total_scanned} items, "
            f"flagged {results.flagged_count} "
            f"({len(results.flagged_shows)} shows, {len(results.flagged_movies)} movies)"
        )

        return results


def build_cleanup_rules(env) -> list[CleanupRule]:
    """Build cleanup rules from environment variables."""
    rules = []

    show_max_age = int(get_env_value(env, "CLEANUP_SHOW_MAX_AGE", "730"))
    movie_max_age = int(get_env_value(env, "CLEANUP_MOVIE_MAX_AGE", "730"))
    exclude_continuing = str_to_bool(get_env_value(env, "CLEANUP_EXCLUDE_CONTINUING", "True"))

    rules.append(CleanupRule(
        name="Stale Shows",
        media_type="show",
        max_age_days=show_max_age,
        exclude_continuing=exclude_continuing,
    ))

    rules.append(CleanupRule(
        name="Stale Movies",
        media_type="movie",
        max_age_days=movie_max_age,
    ))

    return rules


def run_cleanup(servers: list, env) -> CleanupResults | None:
    """
    Run the cleanup scan if enabled. Called after each sync cycle.
    Returns CleanupResults or None if cleanup is disabled.
    """
    cleanup_enabled = str_to_bool(get_env_value(env, "CLEANUP_ENABLED", "False"))

    if not cleanup_enabled:
        logger.debug("CLEANUP: Disabled (CLEANUP_ENABLED=False)")
        return None

    dry_run = str_to_bool(get_env_value(env, "CLEANUP_DRY_RUN", "True"))

    logger.info("CLEANUP: Starting media lifecycle cleanup scan")

    rules = build_cleanup_rules(env)
    engine = CleanupEngine(servers=servers, env=env, dry_run=dry_run)
    results = engine.scan(rules)

    return results
