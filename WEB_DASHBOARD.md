# Ferret Web Dashboard

Ferret includes a built-in web dashboard for monitoring sync status and viewing live logs.

## Features

- **Real-time Sync Status** - See when syncs are running and what's being processed
- **Server Health Monitoring** - Check connection status of Plex, Jellyfin, and Emby servers
- **Live Log Viewer** - WebSocket-powered log streaming directly to your browser
- **Manual Sync Trigger** - Start a sync manually with one click
- **Statistics** - Track total items synced, users, and backfill progress
- **Dark Theme** - Easy-on-the-eyes dark interface
- **Responsive Design** - Works on desktop, tablet, and mobile

## Access

The dashboard is available at:
```
http://localhost:8080
```

Or with your server IP:
```
http://YOUR_SERVER_IP:8080
```

## Docker Setup

The dashboard is enabled by default. Just add port mapping to your Docker configuration:

### Docker Compose
```yaml
services:
  ferret:
    image: git.example.com/global_dynamics/ferret:latest
    ports:
      - "8080:8080"  # Web dashboard
    volumes:
      - ./config/.env:/app/.env
      - /path/to/tautulli/config:/tautulli-data:rw
    environment:
      - PUID=99
      - PGID=100
      - TAUTULLI_DB_PATH=/tautulli-data/tautulli.db
```

### Unraid
Add a port mapping in the template:
- **Container Port:** 8080
- **Host Port:** 8080
- **Protocol:** TCP

Then access the dashboard at `http://tower-ip:8080`

## Usage

### Main Dashboard

- **Sync Status Card**: Shows current sync state, last/next sync time, and statistics
- **Connected Servers**: Displays all configured Plex/Jellyfin/Emby servers with their status
- **Tautulli Backfill**: Shows backfill completion status
- **Live Logs**: Real-time log streaming with auto-scroll

### Manual Sync

Click the "Trigger Manual Sync" button to immediately start a sync cycle outside of the normal schedule.

### Log Viewer

- **Auto-scrolls** to new log entries automatically
- **Manual scroll** disables auto-scroll (scroll to bottom to re-enable)
- **Clear button** to reset the log view
- **Keeps last 500 lines** for performance

## API Endpoints

The dashboard also exposes a REST API:

- `GET /` - Dashboard UI
- `GET /api/status` - Current application status (JSON)
- `GET /api/logs?limit=100` - Recent log lines (JSON)
- `POST /api/sync/trigger` - Trigger manual sync
- `GET /api/health` - Health check endpoint
- `WS /ws/logs` - WebSocket for live logs

## Troubleshooting

### Can't access dashboard

1. Check that port 8080 is mapped correctly
2. Check firewall rules allow port 8080
3. Verify container is running: `docker ps`

### Logs not streaming

1. Check browser console for WebSocket errors
2. Verify WebSocket connections are allowed through any proxies
3. Try refreshing the page

### Server status shows "disconnected"

The dashboard updates server status when syncs run. Wait for the first sync cycle to complete for accurate server status.

## Technology Stack

- **Backend**: FastAPI (Python web framework)
- **Frontend**: htmx (HTML-first dynamic updates)
- **Real-time**: WebSocket for log streaming
- **Styling**: Custom CSS with dark theme
- **State Management**: Thread-safe Python state manager
