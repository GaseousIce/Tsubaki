import json
import os

from libsql_client import create_client

_client = None


async def get_db():
    global _client
    if _client is None:
        url = os.getenv("TURSO_DATABASE_URL")
        auth_token = os.getenv("TURSO_AUTH_TOKEN")
        if not url or not auth_token:
            raise ValueError("TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must be set")
        _client = create_client(url=url, auth_token=auth_token)
    return _client


async def migrate() -> None:
    """Create all tables if they don't exist. Must be called first in setup_hook()."""
    db = await get_db()
    await db.execute("CREATE TABLE IF NOT EXISTS guild_configs (guild_id TEXT PRIMARY KEY, config TEXT NOT NULL)")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS detection_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "guild_id TEXT NOT NULL, "
        "domain TEXT NOT NULL, "
        "reason TEXT NOT NULL, "
        "timestamp TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    await db.execute(
        "CREATE TABLE IF NOT EXISTS custom_blocklist ("
        "domain TEXT PRIMARY KEY, "
        "added_at TEXT NOT NULL DEFAULT (datetime('now')), "
        "source TEXT NOT NULL)"
    )


DEFAULT_GUILD_CONFIG = {
    "enabled": True,
    "action": "timeout",
    "timeout_duration": 604800,
    "alert_channels": [],
    "mod_roles": [],
    "dm_message": None,
    "bypass_role": 0,
}


async def get_guild_config(guild_id: int, default: dict | None = None) -> dict:
    db = await get_db()
    rows = await db.execute(
        "SELECT config FROM guild_configs WHERE guild_id = ?",
        (str(guild_id),),
    )
    base_default = default if default is not None else DEFAULT_GUILD_CONFIG
    if rows.rows:
        merged = base_default.copy()
        merged.update(json.loads(rows.rows[0][0]))
        return merged
    return base_default.copy()


async def get_or_create_guild_config(guild_id: int) -> dict:
    """Return a guild's config, persisting canonical defaults when it is new."""
    db = await get_db()
    rows = await db.execute(
        "SELECT config FROM guild_configs WHERE guild_id = ?",
        (str(guild_id),),
    )
    if rows.rows:
        merged = DEFAULT_GUILD_CONFIG.copy()
        merged.update(json.loads(rows.rows[0][0]))
        return merged

    await db.execute(
        "INSERT OR IGNORE INTO guild_configs (guild_id, config) VALUES (?, ?)",
        (str(guild_id), json.dumps(DEFAULT_GUILD_CONFIG)),
    )
    return await get_guild_config(guild_id)


async def set_guild_config(guild_id: int, config: dict) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO guild_configs (guild_id, config) VALUES (?, ?) "
        "ON CONFLICT(guild_id) DO UPDATE SET config = excluded.config",
        (str(guild_id), json.dumps(config)),
    )


async def update_guild_config(guild_id: int, **kwargs) -> dict:
    cfg = await get_or_create_guild_config(guild_id)
    cfg.update(kwargs)
    await set_guild_config(guild_id, cfg)
    return cfg


# --- Detection log / stats ---


async def log_detection(guild_id: int, domain: str, reason: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO detection_log (guild_id, domain, reason) VALUES (?, ?, ?)",
        (str(guild_id), domain, reason),
    )


async def get_stats(guild_id: int) -> dict:
    db = await get_db()
    total_rs = await db.execute(
        "SELECT COUNT(*) as cnt FROM detection_log WHERE guild_id = ?",
        (str(guild_id),),
    )
    top_rs = await db.execute(
        "SELECT domain, COUNT(*) as cnt FROM detection_log "
        "WHERE guild_id = ? GROUP BY domain ORDER BY cnt DESC LIMIT 10",
        (str(guild_id),),
    )
    last_rs = await db.execute(
        "SELECT domain, reason, timestamp FROM detection_log WHERE guild_id = ? ORDER BY timestamp DESC LIMIT 1",
        (str(guild_id),),
    )
    total = total_rs.rows[0][0] if total_rs.rows else 0
    top = [{"domain": r[0], "count": r[1]} for r in top_rs.rows]
    last = (
        {"domain": last_rs.rows[0][0], "reason": last_rs.rows[0][1], "timestamp": last_rs.rows[0][2]}
        if last_rs.rows
        else None
    )
    return {"total": total, "top": top, "last": last}


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
        "SELECT 1 FROM custom_blocklist WHERE domain = ?",
        (domain,),
    )
    return bool(rows.rows)


async def get_blocklist_source(domain: str) -> str | None:
    db = await get_db()
    rows = await db.execute(
        "SELECT source FROM custom_blocklist WHERE domain = ?",
        (domain,),
    )
    if rows.rows:
        return rows.rows[0]["source"]
    return None


async def remove_from_blocklist(domain: str) -> bool:
    db = await get_db()
    result = await db.execute(
        "DELETE FROM custom_blocklist WHERE domain = ?",
        (domain,),
    )
    return bool(result.rows_affected)
