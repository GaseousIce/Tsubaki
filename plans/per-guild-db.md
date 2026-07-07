# Per-Guild Config Database

Persist guild configs and detection data in [Turso](https://turso.tech) — edge-hosted SQLite, free tier: 9GB storage, 1B requests/month.

## Why Turso

- **Persistent** — survives Render deploys/restarts (unlike ephemeral filesystem)
- **Shared across instances** — if you scale to multiple bot processes, configs are in sync
- **No ORM** — just `libsql` client, SQL queries in Python

## Dependency

```toml
"libsql-client>=0.3.1"
```

## Schema

### `guild_configs` — per-guild feature settings

```sql
CREATE TABLE guild_configs (
  guild_id TEXT PRIMARY KEY,
  config   TEXT NOT NULL  -- JSON blob
);
```

One row per guild. JSON shape matches what each feature expects (e.g. `antiphishing/config.py` defines defaults).

### `detection_log` — stats & audit trail

```sql
CREATE TABLE detection_log (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id  TEXT NOT NULL,
  domain    TEXT NOT NULL,
  reason    TEXT NOT NULL,  -- "blacklist" | "pattern" | "rate_limit"
  timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Stats queries run against this table. The `/antiphishing stats` command uses:
- `SELECT COUNT(*) FROM detection_log WHERE guild_id = ?` → total
- `SELECT domain, COUNT(*) as cnt FROM detection_log WHERE guild_id = ? GROUP BY domain ORDER BY cnt DESC LIMIT 10` → top
- `SELECT * FROM detection_log WHERE guild_id = ? ORDER BY timestamp DESC LIMIT 1` → last detection

### `custom_blocklist` — zero-day findings cache

```sql
CREATE TABLE custom_blocklist (
  domain    TEXT PRIMARY KEY,
  added_at  TEXT NOT NULL DEFAULT (datetime('now')),
  source    TEXT NOT NULL  -- "typosquat" | "manual"
);
```

Domains caught by typosquat scan that aren't in the official blacklist get auto-added here. Future checks hit the blocklist before the pattern scan.

### `typosquat_patterns` — configurable substring patterns

```sql
CREATE TABLE typosquat_patterns (
  pattern   TEXT PRIMARY KEY,
  added_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Managed by slash commands: `/antiphishing patterns add <text>`, `remove`, `list`.

## Environment

Add to `.env` (secret, not committed):

```env
TURSO_DATABASE_URL=libsql://your-db.turso.io
TURSO_AUTH_TOKEN=your-token
```

Paste the same values manually in Render dashboard env vars.

## Module: `src/db.py`

Shared across all features:

```python
import json
import os
from libsql_client import create_client

_client = None

async def get_db():
    global _client
    if _client is None:
        _client = create_client(
            url=os.environ["TURSO_DATABASE_URL"],
            auth_token=os.environ["TURSO_AUTH_TOKEN"],
        )
    return _client

# All functions below assume get_db() succeeds. If Turso is unreachable,
# the caller will raise — caller (e.g. on_message, slash command) should
# catch and log rather than crash the event loop.

# --- Guild configs ---

async def get_guild_config(guild_id: int, default: dict) -> dict:
    db = await get_db()
    rows = await db.execute(
        "SELECT config FROM guild_configs WHERE guild_id = ?", (str(guild_id),),
    )
    if rows:
        merged = default.copy()
        merged.update(json.loads(rows[0]["config"]))
        return merged
    return default

async def set_guild_config(guild_id: int, config: dict) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO guild_configs (guild_id, config) VALUES (?, ?)
           ON CONFLICT(guild_id) DO UPDATE SET config = excluded.config""",
        (str(guild_id), json.dumps(config)),
    )

# --- Detection log / stats ---

async def log_detection(guild_id: int, domain: str, reason: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO detection_log (guild_id, domain, reason) VALUES (?, ?, ?)",
        (str(guild_id), domain, reason),
    )

async def get_stats(guild_id: int) -> dict:
    db = await get_db()
    total = await db.execute(
        "SELECT COUNT(*) as cnt FROM detection_log WHERE guild_id = ?",
        (str(guild_id),),
    )
    top = await db.execute(
        """SELECT domain, COUNT(*) as cnt FROM detection_log
           WHERE guild_id = ? GROUP BY domain ORDER BY cnt DESC LIMIT 10""",
        (str(guild_id),),
    )
    last = await db.execute(
        """SELECT domain, reason, timestamp FROM detection_log
           WHERE guild_id = ? ORDER BY timestamp DESC LIMIT 1""",
        (str(guild_id),),
    )
    return {
        "total": total[0]["cnt"],
        "top": [{"domain": r["domain"], "count": r["cnt"]} for r in top],
        "last": {
            "domain": last[0]["domain"],
            "reason": last[0]["reason"],
            "timestamp": last[0]["timestamp"],
        } if last else None,
    }

# --- Custom blocklist ---

async def add_to_blocklist(domain: str, source: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO custom_blocklist (domain, source) VALUES (?, ?)",
        (domain, source),
    )

async def is_in_blocklist(domain: str) -> bool:
    db = await get_db()
    rows = await db.execute(
        "SELECT 1 FROM custom_blocklist WHERE domain = ?", (domain,),
    )
    return bool(rows)

# --- Typosquat patterns ---

async def get_patterns() -> list[str]:
    db = await get_db()
    rows = await db.execute("SELECT pattern FROM typosquat_patterns ORDER BY pattern")
    return [r["pattern"] for r in rows]

async def add_pattern(pattern: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO typosquat_patterns (pattern) VALUES (?)", (pattern,),
    )

async def remove_pattern(pattern: str) -> bool:
    db = await get_db()
    result = await db.execute(
        "DELETE FROM typosquat_patterns WHERE pattern = ?", (pattern,),
    )
    return bool(result.rows_affected)
```

> **Confirmed:** `ResultSet.rows_affected` exists in `libsql-client>=0.3.1` (see `result.py` in the package source).

## `render.yaml` env vars

Add these to `render.yaml` under `envVars`:

```yaml
          - key: TURSO_DATABASE_URL
            sync: false
          - key: TURSO_AUTH_TOKEN
            sync: false
```

## Migration

Call `migrate()` from `main.py` on startup. Must be the first async operation in `setup_hook()` — anti-phishing and other features depend on the tables existing.

```python
async def migrate():
    db = await get_db()
    await db.execute("CREATE TABLE IF NOT EXISTS guild_configs (guild_id TEXT PRIMARY KEY, config TEXT NOT NULL)")
    await db.execute("CREATE TABLE IF NOT EXISTS detection_log (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL, domain TEXT NOT NULL, reason TEXT NOT NULL, timestamp TEXT NOT NULL DEFAULT (datetime('now')))")
    await db.execute("CREATE TABLE IF NOT EXISTS custom_blocklist (domain TEXT PRIMARY KEY, added_at TEXT NOT NULL DEFAULT (datetime('now')), source TEXT NOT NULL)")
    await db.execute("CREATE TABLE IF NOT EXISTS typosquat_patterns (pattern TEXT PRIMARY KEY, added_at TEXT NOT NULL DEFAULT (datetime('now')))")
```

## Usage

Each feature's config module swaps file I/O for `src.db` calls. Detection pipeline calls `log_detection()` + `add_to_blocklist()` when catching zero-day domains. Stats are queried from `detection_log` on demand.

---

## TODO

- [ ] Add `libsql-client` to `pyproject.toml` dependencies
- [ ] Add `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` to `.env.example`
- [ ] Create `src/db.py` — all functions above + `migrate()`
- [ ] Call `migrate()` from `main.py` on startup
- [ ] Create Turso database on turso.tech, paste URL + token in `.env` and Render dashboard
- [ ] Add `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` to `render.yaml` `envVars` (both `sync: false`)
- [ ] Run `ruff check + format` on `src/`
