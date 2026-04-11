import os
import time
import traceback
import json
import sys
from dotenv import dotenv_values
from time import sleep, perf_counter
from loguru import logger

from src.emby import Emby
from src.jellyfin import Jellyfin
from src.plex import Plex
from src.library import setup_libraries
from src.functions import (
    parse_string_to_list,
    str_to_bool,
    get_env_value,
)
from src.users import setup_users
from src.watched import (
    cleanup_watched,
    merge_server_watched,
)
from src.black_white import setup_black_white_lists
from src.connection import generate_server_connections
from src.cleanup import run_cleanup


# Track if logger has been configured when preserving handlers
_logger_configured = False

def configure_logger(log_file: str = "log.log", debug_level: str = "INFO", preserve_handlers: bool = False) -> None:
    global _logger_configured

    # Remove default logger to configure our own
    # If preserve_handlers is True, keep existing handlers (for web dashboard)
    if not preserve_handlers:
        logger.remove()
        _logger_configured = False
    elif _logger_configured:
        # Already configured with preserved handlers, skip to avoid duplicates
        return

    # Log what level we're configuring (only first time)
    if not _logger_configured:
        print(f"Configuring logger with level: {debug_level}, preserve_handlers: {preserve_handlers}")

    # Choose log level based on environment
    # If in debug mode with a "debug" level, use DEBUG; otherwise, default to INFO.

    if debug_level not in ["INFO", "DEBUG", "TRACE"]:
        logger.add(sys.stdout)
        raise Exception(
            f"Invalid DEBUG_LEVEL {debug_level}, please choose between INFO, DEBUG, TRACE"
        )

    # Add a sink for file logging and the console.
    logger.add(log_file, level=debug_level, mode="w")
    if not preserve_handlers:
        logger.add(sys.stdout, level=debug_level)

    if preserve_handlers:
        _logger_configured = True


def should_sync_server(
    env,
    server_1: Plex | Jellyfin | Emby,
    server_2: Plex | Jellyfin | Emby,
) -> bool:
    sync_from_plex_to_jellyfin = str_to_bool(
        get_env_value(env, "SYNC_FROM_PLEX_TO_JELLYFIN", "True")
    )
    sync_from_plex_to_plex = str_to_bool(
        get_env_value(env, "SYNC_FROM_PLEX_TO_PLEX", "True")
    )
    sync_from_plex_to_emby = str_to_bool(
        get_env_value(env, "SYNC_FROM_PLEX_TO_EMBY", "True")
    )

    sync_from_jelly_to_plex = str_to_bool(
        get_env_value(env, "SYNC_FROM_JELLYFIN_TO_PLEX", "True")
    )
    sync_from_jelly_to_jellyfin = str_to_bool(
        get_env_value(env, "SYNC_FROM_JELLYFIN_TO_JELLYFIN", "True")
    )
    sync_from_jelly_to_emby = str_to_bool(
        get_env_value(env, "SYNC_FROM_JELLYFIN_TO_EMBY", "True")
    )

    sync_from_emby_to_plex = str_to_bool(
        get_env_value(env, "SYNC_FROM_EMBY_TO_PLEX", "True")
    )
    sync_from_emby_to_jellyfin = str_to_bool(
        get_env_value(env, "SYNC_FROM_EMBY_TO_JELLYFIN", "True")
    )
    sync_from_emby_to_emby = str_to_bool(
        get_env_value(env, "SYNC_FROM_EMBY_TO_EMBY", "True")
    )

    if isinstance(server_1, Plex):
        if isinstance(server_2, Jellyfin) and not sync_from_plex_to_jellyfin:
            logger.info("Sync from plex -> jellyfin is disabled")
            return False

        if isinstance(server_2, Emby) and not sync_from_plex_to_emby:
            logger.info("Sync from plex -> emby is disabled")
            return False

        if isinstance(server_2, Plex) and not sync_from_plex_to_plex:
            logger.info("Sync from plex -> plex is disabled")
            return False

    if isinstance(server_1, Jellyfin):
        if isinstance(server_2, Plex) and not sync_from_jelly_to_plex:
            logger.info("Sync from jellyfin -> plex is disabled")
            return False

        if isinstance(server_2, Jellyfin) and not sync_from_jelly_to_jellyfin:
            logger.info("Sync from jellyfin -> jellyfin is disabled")
            return False

        if isinstance(server_2, Emby) and not sync_from_jelly_to_emby:
            logger.info("Sync from jellyfin -> emby is disabled")
            return False

    if isinstance(server_1, Emby):
        if isinstance(server_2, Plex) and not sync_from_emby_to_plex:
            logger.info("Sync from emby -> plex is disabled")
            return False

        if isinstance(server_2, Jellyfin) and not sync_from_emby_to_jellyfin:
            logger.info("Sync from emby -> jellyfin is disabled")
            return False

        if isinstance(server_2, Emby) and not sync_from_emby_to_emby:
            logger.info("Sync from emby -> emby is disabled")
            return False

    return True


def main_loop(env) -> None:
    # Import web state if available
    try:
        from src.web.state import app_state
        web_dashboard_enabled = True
    except ImportError:
        web_dashboard_enabled = False

    if web_dashboard_enabled:
        app_state.set_syncing(True, "Initializing sync")

    dryrun = str_to_bool(get_env_value(env, "DRYRUN", "False"))
    logger.info(f"Dryrun: {dryrun}")

    if web_dashboard_enabled:
        app_state.set_dryrun(dryrun)

    user_mapping_env = get_env_value(env, "USER_MAPPING", None)
    user_mapping = None
    if user_mapping_env:
        user_mapping = json.loads(user_mapping_env.lower())
    logger.info(f"User Mapping: {user_mapping}")

    library_mapping_env = get_env_value(env, "LIBRARY_MAPPING", None)
    library_mapping = None
    if library_mapping_env:
        library_mapping = json.loads(library_mapping_env)
    logger.info(f"Library Mapping: {library_mapping}")

    # Create (black/white)lists
    logger.info("Creating (black/white)lists")
    blacklist_library = parse_string_to_list(
        get_env_value(env, "BLACKLIST_LIBRARY", None)
    )
    whitelist_library = parse_string_to_list(
        get_env_value(env, "WHITELIST_LIBRARY", None)
    )
    blacklist_library_type = parse_string_to_list(
        get_env_value(env, "BLACKLIST_LIBRARY_TYPE", None)
    )
    whitelist_library_type = parse_string_to_list(
        get_env_value(env, "WHITELIST_LIBRARY_TYPE", None)
    )
    blacklist_users = parse_string_to_list(get_env_value(env, "BLACKLIST_USERS", None))
    whitelist_users = parse_string_to_list(get_env_value(env, "WHITELIST_USERS", None))

    (
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        blacklist_users,
        whitelist_users,
    ) = setup_black_white_lists(
        blacklist_library,
        whitelist_library,
        blacklist_library_type,
        whitelist_library_type,
        blacklist_users,
        whitelist_users,
        library_mapping,
        user_mapping,
    )

    # Create server connections
    logger.info("Creating server connections")
    servers = generate_server_connections(env)

    for server_1 in servers:
        # If server is the final server in the list, then we are done with the loop
        if server_1 == servers[-1]:
            break

        # Store a copy of server_1_watched that way it can be used multiple times without having to regather everyones watch history every single time
        server_1_watched = None

        # Start server_2 at the next server in the list
        for server_2 in servers[servers.index(server_1) + 1 :]:
            # Check if server 1 and server 2 are going to be synced in either direction, skip if not
            if not should_sync_server(
                env, server_1, server_2
            ) and not should_sync_server(env, server_2, server_1):
                continue

            # Retry up to 3 times with exponential backoff
            for attempt in range(3):
                try:
                    logger.info(f"Server 1: {type(server_1)}: {server_1.info()}")
                    logger.info(f"Server 2: {type(server_2)}: {server_2.info()}")

                    if web_dashboard_enabled:
                        # Get short server names for display
                        s1_name = server_1.info(name_only=True) if hasattr(server_1, 'info') and isinstance(server_1, (Jellyfin, Emby)) else server_1.plex.friendlyName
                        s2_name = server_2.info(name_only=True) if hasattr(server_2, 'info') and isinstance(server_2, (Jellyfin, Emby)) else server_2.plex.friendlyName
                        app_state.set_syncing(True, f"{s1_name} ↔ {s2_name}")

                    # Create users list
                    logger.info("Creating users list")
                    server_1_users, server_2_users = setup_users(
                        server_1, server_2, blacklist_users, whitelist_users, user_mapping
                    )

                    server_1_libraries, server_2_libraries = setup_libraries(
                        server_1,
                        server_2,
                        blacklist_library,
                        blacklist_library_type,
                        whitelist_library,
                        whitelist_library_type,
                        library_mapping,
                    )
                    logger.info(f"Server 1 syncing libraries: {server_1_libraries}")
                    logger.info(f"Server 2 syncing libraries: {server_2_libraries}")

                    logger.info("Creating watched lists")
                    server_1_watched = server_1.get_watched(
                        server_1_users, server_1_libraries, server_1_watched
                    )
                    logger.info("Finished creating watched list server 1")

                    server_2_watched = server_2.get_watched(server_2_users, server_2_libraries)
                    logger.info("Finished creating watched list server 2")

                    logger.trace(f"Server 1 watched: {server_1_watched}")
                    logger.trace(f"Server 2 watched: {server_2_watched}")

                    logger.info("Cleaning Server 1 Watched")
                    server_1_watched_filtered = cleanup_watched(
                        server_1_watched, server_2_watched, user_mapping, library_mapping
                    )

                    logger.info("Cleaning Server 2 Watched")
                    server_2_watched_filtered = cleanup_watched(
                        server_2_watched, server_1_watched, user_mapping, library_mapping
                    )

                    logger.debug(
                        f"server 1 watched that needs to be synced to server 2:\n{server_1_watched_filtered}",
                    )
                    logger.debug(
                        f"server 2 watched that needs to be synced to server 1:\n{server_2_watched_filtered}",
                    )

                    # Count items to sync for stats
                    items_synced = 0

                    if should_sync_server(env, server_2, server_1):
                        logger.info(f"Syncing {server_2.info()} -> {server_1.info()}")
                        if web_dashboard_enabled:
                            app_state.set_syncing(True, f"{s2_name} → {s1_name}")

                        # Count items in this direction
                        for user_data in server_2_watched_filtered.values():
                            for lib_data in user_data.libraries.values():
                                items_synced += len(lib_data.movies)
                                for series in lib_data.series:
                                    items_synced += len(series.episodes)

                        # Add server_2_watched_filtered to server_1_watched that way the stored version isn't stale for the next server
                        if not dryrun:
                            server_1_watched = merge_server_watched(
                                server_1_watched,
                                server_2_watched_filtered,
                                user_mapping,
                                library_mapping,
                            )

                        server_1.update_watched(
                            server_2_watched_filtered,
                            user_mapping,
                            library_mapping,
                            dryrun,
                        )

                    if should_sync_server(env, server_1, server_2):
                        logger.info(f"Syncing {server_1.info()} -> {server_2.info()}")
                        if web_dashboard_enabled:
                            app_state.set_syncing(True, f"{s1_name} → {s2_name}")

                        # Count items in this direction
                        for user_data in server_1_watched_filtered.values():
                            for lib_data in user_data.libraries.values():
                                items_synced += len(lib_data.movies)
                                for series in lib_data.series:
                                    items_synced += len(series.episodes)

                        server_2.update_watched(
                            server_1_watched_filtered,
                            user_mapping,
                            library_mapping,
                            dryrun,
                        )

                    # Update dashboard stats after successful sync of this pair
                    if web_dashboard_enabled:
                        total_users = len(set(
                            list(server_1_watched.keys()) + list(server_2_watched.keys())
                        ))
                        app_state.update_stats(items_synced=items_synced, users=total_users)

                    break  # Success, no need to retry

                except Exception as e:
                    # Get server names for error message
                    s1_name = "Unknown"
                    s2_name = "Unknown"
                    try:
                        s1_name = server_1.info(name_only=True) if hasattr(server_1, 'info') and isinstance(server_1, (Jellyfin, Emby)) else server_1.plex.friendlyName
                        s2_name = server_2.info(name_only=True) if hasattr(server_2, 'info') and isinstance(server_2, (Jellyfin, Emby)) else server_2.plex.friendlyName
                    except Exception:
                        pass

                    if attempt < 2:
                        logger.warning(f"Sync failed between {s1_name} and {s2_name} (attempt {attempt + 1}/3), retrying in {2 ** attempt}s: {e}")
                        time.sleep(2 ** attempt)
                    else:
                        logger.error(f"Sync failed between {s1_name} and {s2_name} after 3 attempts: {e}")
                        logger.warning("Continuing with remaining server pairs...")

    # Run cleanup scan after sync completes
    try:
        if web_dashboard_enabled:
            app_state.set_syncing(True, "Running cleanup scan")
        cleanup_results = run_cleanup(servers, env)
        if cleanup_results is not None and web_dashboard_enabled:
            app_state.set_cleanup_results(cleanup_results.to_dict())
            # Expose the persistent CleanupDB to the web layer for exclusions
            from src.cleanup_db import CleanupDB
            from src.functions import get_env_value as _gev
            db_path = _gev(env, "CLEANUP_DB_PATH", "/app/data/cleanup.db")
            app_state.set_cleanup_state(CleanupDB(db_path))
    except Exception as e:
        logger.error(f"Cleanup scan failed: {e}")

    # Mark sync as complete
    if web_dashboard_enabled:
        app_state.set_syncing(False)


@logger.catch
def main() -> None:
    # Get environment variables
    env_file = get_env_value(None, "ENV_FILE", ".env")
    env = dotenv_values(env_file)

    run_only_once = str_to_bool(get_env_value(env, "RUN_ONLY_ONCE", "False"))
    sleep_duration = float(get_env_value(env, "SLEEP_DURATION", "3600"))
    log_file = get_env_value(env, "LOG_FILE", "log.log")
    debug_level = get_env_value(env, "DEBUG_LEVEL", "INFO")
    if debug_level:
        debug_level = debug_level.upper()

    times: list[float] = []
    # Check if running with web dashboard
    preserve_web_handlers = os.getenv('FERRET_WEB_DASHBOARD') == '1'

    # Import web state if available
    web_dashboard_enabled = False
    if preserve_web_handlers:
        try:
            from src.web.state import app_state
            web_dashboard_enabled = True
        except ImportError:
            pass

    while True:
        try:
            start = perf_counter()
            # Re-read .env at the start of each cycle so web UI setting
            # changes are picked up without a container restart.
            env = dotenv_values(env_file)
            run_only_once = str_to_bool(get_env_value(env, "RUN_ONLY_ONCE", "False"))
            sleep_duration = float(get_env_value(env, "SLEEP_DURATION", "3600"))
            log_file = get_env_value(env, "LOG_FILE", "log.log")
            debug_level = get_env_value(env, "DEBUG_LEVEL", "INFO")
            if debug_level:
                debug_level = debug_level.upper()

            # Reconfigure the logger on each loop so the logs are rotated on each run
            # Preserve handlers if running with web dashboard
            configure_logger(log_file, debug_level, preserve_handlers=preserve_web_handlers)
            main_loop(env)
            end = perf_counter()
            times.append(end - start)

            if len(times) > 0:
                logger.info(f"Average time: {sum(times) / len(times)}")

            if run_only_once:
                break

            logger.info(f"Looping in {sleep_duration}")

            # Check for manual sync requests from web dashboard
            if web_dashboard_enabled:
                # Sleep in small intervals to check for manual sync requests
                elapsed = 0
                while elapsed < sleep_duration:
                    if app_state.manual_sync_requested:
                        logger.info("Web: Manual sync request detected, starting sync now")
                        app_state.clear_manual_sync_request()
                        break
                    sleep(1)
                    elapsed += 1
            else:
                sleep(sleep_duration)

        except Exception as error:
            logger.error(error)

            logger.error(traceback.format_exc())

            if run_only_once:
                break

            logger.info(f"Retrying in {sleep_duration}")
            sleep(sleep_duration)

        except KeyboardInterrupt:
            if len(times) > 0:
                logger.info(f"Average time: {sum(times) / len(times)}")
            logger.info("Exiting")
            sys.exit(0)
