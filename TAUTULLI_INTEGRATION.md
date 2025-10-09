# Tautulli Integration

Ferret can write playback history directly to Tautulli's database, allowing synced content to appear in Tautulli's history as if it was actually played.

## Why This Feature?

Plex's API marks items as watched, but doesn't create actual playback history entries. This means:
- ❌ Tautulli doesn't see the activity
- ❌ Maintainerr can't track synced watches
- ❌ No history/statistics for synced content

With Tautulli integration:
- ✅ Items marked as watched in Plex
- ✅ Playback history entries created in Tautulli
- ✅ Maintainerr can see and track the activity
- ✅ Full statistics and history tracking

## Setup

### 1. Find Your Tautulli Database

The database file is called `tautulli.db` and is typically located at:

**Docker:**
```
/path/to/tautulli/config/tautulli.db
```

**Bare Metal:**
- Linux: `~/.config/Tautulli/tautulli.db`
- Windows: `%APPDATA%\Tautulli\tautulli.db`
- macOS: `~/Library/Application Support/Tautulli/tautulli.db`

### 2. Configure Ferret

**Option A: Docker** (Recommended)

Add a volume mount and environment variable:

```yaml
# docker-compose.yml
services:
  ferret:
    image: git.bitstorm.ca/global_dynamics/ferret:latest
    volumes:
      - ./config/.env:/app/.env
      - /path/to/tautulli/config:/tautulli-data:ro  # Read-only mount
    environment:
      - TAUTULLI_DB_PATH=/tautulli-data/tautulli.db
```

Or with docker run:
```bash
docker run -d \
  -v "$(pwd)/.env:/app/.env" \
  -v "/path/to/tautulli/config:/tautulli-data:ro" \
  -e TAUTULLI_DB_PATH=/tautulli-data/tautulli.db \
  git.bitstorm.ca/global_dynamics/ferret:latest
```

**Option B: Bare Metal**

Edit your `.env` file:
```bash
TAUTULLI_DB_PATH = "/full/path/to/tautulli.db"
```

### 3. Verify It's Working

Run with debug logging enabled:
```bash
DEBUG_LEVEL = "DEBUG"
```

You should see:
```
INFO | Tautulli: History logging enabled to /path/to/tautulli.db
DEBUG | Tautulli: Logged watch for MovieName by UserName (100% watched)
```

### 4. Check Tautulli

After a sync:
1. Open Tautulli web interface
2. Go to **History** tab
3. Look for entries with:
   - Player: `ferret`
   - Platform: `Ferret`
   - IP Address: `sync`

## Important Notes

### Database Permissions

**Docker:** The container needs read/write access to the database:
- Use `:rw` instead of `:ro` if you get permission errors
- Make sure file permissions allow the container user to write

**Bare Metal:** The user running Ferret needs write access to `tautulli.db`

### Database Safety

- The integration writes directly to Tautulli's SQLite database
- **Always backup your Tautulli database before enabling this feature**
- The writes are minimal and safe (only inserts, no updates/deletes)
- If errors occur, the sync will still complete (Tautulli logging is optional)

### Limitations

- History entries are created with the current timestamp (not the original watch date from the source server)
- The "IP Address" field shows `sync` to distinguish from real playback
- Player is identified as `ferret`

## Troubleshooting

### "Database not found" Warning

```
WARNING | Tautulli: Database not found at /path/to/tautulli.db, history logging disabled
```

**Fix:**
1. Verify the path is correct
2. Check that the database file exists
3. Ensure proper volume mounts (Docker)

### "Database error" Warnings

```
WARNING | Tautulli: Database error: attempt to write a readonly database
```

**Fix:**
1. Check file permissions
2. For Docker, use `:rw` instead of `:ro` on the volume mount
3. Make sure Tautulli isn't locking the database (normal during writes)

### No Entries in Tautulli

1. Check debug logs for Tautulli messages
2. Verify `TAUTULLI_DB_PATH` is set correctly
3. Make sure a sync actually occurred (items were marked)
4. Check Tautulli's history filter settings

## Disabling Tautulli Integration

To disable, simply comment out or remove:
```bash
# TAUTULLI_DB_PATH = ""
```

Ferret will continue to work normally, just without Tautulli history logging.
