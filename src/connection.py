from typing import Literal
from loguru import logger

from src.functions import str_to_bool, get_env_value
from src.plex import Plex
from src.jellyfin import Jellyfin
from src.emby import Emby

# Import web state if available
try:
    from src.web.state import app_state
    WEB_DASHBOARD_ENABLED = True
except ImportError:
    WEB_DASHBOARD_ENABLED = False


def jellyfin_emby_server_connection(
    env,
    server_baseurl: str,
    server_token: str,
    server_type: Literal["jellyfin", "emby"],
) -> list[Jellyfin | Emby]:
    servers: list[Jellyfin | Emby] = []
    server: Jellyfin | Emby

    server_baseurls = server_baseurl.split(",")
    server_tokens = server_token.split(",")

    if len(server_baseurls) != len(server_tokens):
        raise Exception(
            f"{server_type.upper()}_BASEURL and {server_type.upper()}_TOKEN must have the same number of entries"
        )

    for i, base_url in enumerate(server_baseurls):
        try:
            base_url = base_url.strip()
            if base_url[-1] == "/":
                base_url = base_url[:-1]

            logger.info(f"Connecting to {server_type.capitalize()} server at {base_url}...")

            if server_type == "jellyfin":
                server = Jellyfin(
                    env=env, base_url=base_url, token=server_tokens[i].strip()
                )
                servers.append(server)
                # Register server with web dashboard (after init so server_name is available)
                if WEB_DASHBOARD_ENABLED:
                    logger.info(f"Web: Registering Jellyfin server: {server.server_name}")
                    app_state.add_server(
                        name=server.server_name,
                        server_type="Jellyfin",
                        status="connected",
                        version=getattr(server, 'version', '')
                    )
                logger.info(f"Successfully connected to Jellyfin server: {server.server_name}")

            elif server_type == "emby":
                server = Emby(env=env, base_url=base_url, token=server_tokens[i].strip())
                servers.append(server)
                # Register server with web dashboard (after init so server_name is available)
                if WEB_DASHBOARD_ENABLED:
                    logger.info(f"Web: Registering Emby server: {server.server_name}")
                    app_state.add_server(
                        name=server.server_name,
                        server_type="Emby",
                        status="connected",
                        version=getattr(server, 'version', '')
                    )
                logger.info(f"Successfully connected to Emby server: {server.server_name}")
            else:
                raise Exception("Unknown server type")

            logger.debug(f"{server_type} Server {i} info: {server.info()}")

        except Exception as e:
            logger.error(f"Failed to connect to {server_type.capitalize()} server at {base_url}: {e}")
            # Register failed server in dashboard
            if WEB_DASHBOARD_ENABLED:
                app_state.add_server(
                    name=f"{server_type.capitalize()} ({base_url})",
                    server_type=server_type.capitalize(),
                    status="disconnected",
                    version=""
                )
            logger.warning(f"Continuing with remaining servers...")

    return servers


def generate_server_connections(env) -> list[Plex | Jellyfin | Emby]:
    servers: list[Plex | Jellyfin | Emby] = []

    plex_baseurl_str: str | None = get_env_value(env, "PLEX_BASEURL", None)
    plex_token_str: str | None = get_env_value(env, "PLEX_TOKEN", None)
    plex_username_str: str | None = get_env_value(env, "PLEX_USERNAME", None)
    plex_password_str: str | None = get_env_value(env, "PLEX_PASSWORD", None)
    plex_servername_str: str | None = get_env_value(env, "PLEX_SERVERNAME", None)
    ssl_bypass = str_to_bool(get_env_value(env, "SSL_BYPASS", "False"))

    if plex_baseurl_str and plex_token_str:
        plex_baseurl = plex_baseurl_str.split(",")
        plex_token = plex_token_str.split(",")

        if len(plex_baseurl) != len(plex_token):
            raise Exception(
                "PLEX_BASEURL and PLEX_TOKEN must have the same number of entries"
            )

        for i, url in enumerate(plex_baseurl):
            try:
                logger.info(f"Connecting to Plex server at {url.strip()}...")
                server = Plex(
                    env,
                    base_url=url.strip(),
                    token=plex_token[i].strip(),
                    user_name=None,
                    password=None,
                    server_name=None,
                    ssl_bypass=ssl_bypass,
                )

                logger.debug(f"Plex Server {i} info: {server.info()}")

                # Register server with web dashboard
                if WEB_DASHBOARD_ENABLED:
                    logger.info(f"Web: Registering Plex server: {server.plex.friendlyName}")
                    app_state.add_server(
                        name=server.plex.friendlyName,
                        server_type="Plex",
                        status="connected",
                        version=server.plex.version
                    )

                logger.info(f"Successfully connected to Plex server: {server.plex.friendlyName}")

                # Backfill will be done after all servers are connected

                servers.append(server)

            except Exception as e:
                logger.error(f"Failed to connect to Plex server at {url.strip()}: {e}")
                # Register failed server in dashboard
                if WEB_DASHBOARD_ENABLED:
                    app_state.add_server(
                        name=f"Plex ({url.strip()})",
                        server_type="Plex",
                        status="disconnected",
                        version=""
                    )
                logger.warning(f"Continuing with remaining servers...")

    if plex_username_str and plex_password_str and plex_servername_str:
        plex_username = plex_username_str.split(",")
        plex_password = plex_password_str.split(",")
        plex_servername = plex_servername_str.split(",")

        if len(plex_username) != len(plex_password) or len(plex_username) != len(
            plex_servername
        ):
            raise Exception(
                "PLEX_USERNAME, PLEX_PASSWORD and PLEX_SERVERNAME must have the same number of entries"
            )

        for i, username in enumerate(plex_username):
            try:
                logger.info(f"Connecting to Plex server '{plex_servername[i].strip()}' as user '{username.strip()}'...")
                server = Plex(
                    env,
                    base_url=None,
                    token=None,
                    user_name=username.strip(),
                    password=plex_password[i].strip(),
                    server_name=plex_servername[i].strip(),
                    ssl_bypass=ssl_bypass,
                )

                logger.debug(f"Plex Server {i} info: {server.info()}")

                # Register server with web dashboard
                if WEB_DASHBOARD_ENABLED:
                    logger.info(f"Web: Registering Plex server: {server.plex.friendlyName}")
                    app_state.add_server(
                        name=server.plex.friendlyName,
                        server_type="Plex",
                        status="connected",
                        version=server.plex.version
                    )

                logger.info(f"Successfully connected to Plex server: {server.plex.friendlyName}")

                # Backfill will be done after all servers are connected

                servers.append(server)

            except Exception as e:
                logger.error(f"Failed to connect to Plex server '{plex_servername[i].strip()}': {e}")
                # Register failed server in dashboard
                if WEB_DASHBOARD_ENABLED:
                    app_state.add_server(
                        name=f"Plex ({plex_servername[i].strip()})",
                        server_type="Plex",
                        status="disconnected",
                        version=""
                    )
                logger.warning(f"Continuing with remaining servers...")

    jellyfin_baseurl = get_env_value(env, "JELLYFIN_BASEURL", None)
    jellyfin_token = get_env_value(env, "JELLYFIN_TOKEN", None)
    if jellyfin_baseurl and jellyfin_token:
        servers.extend(
            jellyfin_emby_server_connection(
                env, jellyfin_baseurl, jellyfin_token, "jellyfin"
            )
        )

    emby_baseurl = get_env_value(env, "EMBY_BASEURL", None)
    emby_token = get_env_value(env, "EMBY_TOKEN", None)
    logger.debug(f"Emby config check: baseurl={emby_baseurl}, token={'***' if emby_token else None}")
    if emby_baseurl and emby_token:
        logger.info("Connecting to Emby server(s)...")
        emby_servers = jellyfin_emby_server_connection(env, emby_baseurl, emby_token, "emby")
        logger.info(f"Connected to {len(emby_servers)} Emby server(s)")
        servers.extend(emby_servers)

    # Now backfill Tautulli for all Plex servers (after all connections are established)
    # Only run if TAUTULLI_BACKFILL_ENABLED is True
    tautulli_backfill_enabled = str_to_bool(get_env_value(env, "TAUTULLI_BACKFILL_ENABLED", "False"))

    if tautulli_backfill_enabled:
        try:
            logger.info("All servers connected. Starting Tautulli backfill for Plex servers...")
            total_backfill_count = 0
            backfill_ran = False

            for server in servers:
                if isinstance(server, Plex):
                    try:
                        if WEB_DASHBOARD_ENABLED:
                            app_state.set_syncing(True, "Backfilling Tautulli")
                        count = server.backfill_all_users()
                        backfill_ran = True
                        if count and isinstance(count, int):
                            total_backfill_count += count
                    except Exception as e:
                        logger.error(f"Tautulli backfill failed for server {server.plex.friendlyName}: {e}")
                        logger.warning("Continuing with remaining servers...")

            # Mark backfill as complete if it ran (even if no items were added)
            if WEB_DASHBOARD_ENABLED and backfill_ran:
                app_state.set_backfill_status(complete=True, count=total_backfill_count)
                logger.info(f"Web: Backfill complete - {total_backfill_count} items added to Tautulli")
        except Exception as e:
            logger.error(f"Tautulli backfill process failed: {e}")
            if WEB_DASHBOARD_ENABLED:
                app_state.set_backfill_status(complete=True, count=0)
    else:
        logger.info("Tautulli backfill is disabled (TAUTULLI_BACKFILL_ENABLED=False)")
        if WEB_DASHBOARD_ENABLED:
            app_state.set_backfill_status(complete=True, count=0)

    return servers
