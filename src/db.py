import asyncio
import copy
import inspect
import json
import logging
import os

from libsql_client import create_client

logger = logging.getLogger("tsubaki.db")

_client = None
_client_lock: asyncio.Lock | None = None
_guild_locks: dict[int, asyncio.Lock] = {}
_config_cache: dict[int, dict] = {}
MAX_CONFIG_CACHE_SIZE = 1000


def _get_client_lock() -> asyncio.Lock:
    global _client_lock
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    return _client_lock


def _get_guild_lock(guild_id: int) -> asyncio.Lock:
    if guild_id not in _guild_locks:
        _guild_locks[guild_id] = asyncio.Lock()
    return _guild_locks[guild_id]


def _cache_get(guild_id: int) -> dict | None:
    if guild_id in _config_cache:
        val = _config_cache.pop(guild_id)
        _config_cache[guild_id] = val
        return copy.deepcopy(val)
    return None


def _cache_set(guild_id: int, config: dict) -> None:
    if len(_config_cache) >= MAX_CONFIG_CACHE_SIZE and guild_id not in _config_cache:
        oldest_key = next(iter(_config_cache))
        _config_cache.pop(oldest_key, None)
    _config_cache[guild_id] = copy.deepcopy(config)


def clear_config_cache(guild_id: int | None = None) -> None:
    """Clear all or a single guild's cache entry."""
    if guild_id is None:
        _config_cache.clear()
        _guild_locks.clear()
    else:
        _config_cache.pop(guild_id, None)
        _guild_locks.pop(guild_id, None)


async def get_db():
    global _client
    if _client is None or getattr(_client, "closed", False):
        async with _get_client_lock():
            if _client is None or getattr(_client, "closed", False):
                url = os.getenv("TURSO_DATABASE_URL")
                auth_token = os.getenv("TURSO_AUTH_TOKEN")
                if not url or not auth_token:
                    raise ValueError("TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must be set")
                _client = create_client(url=url, auth_token=auth_token)
    return _client


async def close_db() -> None:
    """Close the database client session and release resources."""
    global _client
    if _client is not None:
        client = _client
        _client = None
        if hasattr(client, "close"):
            try:
                res = client.close()
                if inspect.isawaitable(res):
                    await res
            except Exception as exc:
                logger.warning("Error closing database client: %s", exc)


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
        "content TEXT, "
        "attachments TEXT, "
        "timestamp TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    await db.execute(
        "CREATE TABLE IF NOT EXISTS custom_blocklist ("
        "domain TEXT PRIMARY KEY COLLATE NOCASE, "
        "added_at TEXT NOT NULL DEFAULT (datetime('now')), "
        "source TEXT NOT NULL)"
    )
    await db.execute(
        "CREATE TABLE IF NOT EXISTS typosquat_patterns ("
        "pattern TEXT PRIMARY KEY, "
        "target_domain TEXT NOT NULL, "
        "added_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_detection_log_guild_timestamp ON detection_log (guild_id, timestamp DESC)"
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_detection_log_guild_domain ON detection_log (guild_id, domain)")
    table_info = await db.execute("PRAGMA table_info(detection_log)")
    existing_cols = {row[1] for row in table_info.rows} if table_info.rows else set()
    if existing_cols:
        for col in ("content", "attachments"):
            if col not in existing_cols:
                try:
                    await db.execute(f"ALTER TABLE detection_log ADD COLUMN {col} TEXT")
                except Exception as exc:
                    if "duplicate column" not in str(exc).lower():
                        raise


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
    if default is None:
        cached = _cache_get(guild_id)
        if cached is not None:
            return cached

    db = await get_db()
    rows = await db.execute(
        "SELECT config FROM guild_configs WHERE guild_id = ?",
        (str(guild_id),),
    )
    base_default = default if default is not None else DEFAULT_GUILD_CONFIG
    if rows.rows:
        merged = copy.deepcopy(base_default)
        raw_config = rows.rows[0][0]
        try:
            stored_data = json.loads(raw_config)
            if isinstance(stored_data, dict):
                merged.update(stored_data)
            else:
                logger.warning("Corrupt non-dict config JSON for guild %s; using defaults", guild_id)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error("Failed to parse config JSON for guild %s: %s; falling back to defaults", guild_id, exc)
        if default is None:
            _cache_set(guild_id, merged)
        return copy.deepcopy(merged)
    return copy.deepcopy(base_default)


async def get_or_create_guild_config(guild_id: int) -> dict:
    """Return a guild's config, persisting canonical defaults when it is new."""
    cached = _cache_get(guild_id)
    if cached is not None:
        return cached

    db = await get_db()
    rows = await db.execute(
        "SELECT config FROM guild_configs WHERE guild_id = ?",
        (str(guild_id),),
    )
    if rows.rows:
        merged = copy.deepcopy(DEFAULT_GUILD_CONFIG)
        raw_config = rows.rows[0][0]
        try:
            stored_data = json.loads(raw_config)
            if isinstance(stored_data, dict):
                merged.update(stored_data)
            else:
                logger.warning("Corrupt non-dict config JSON for guild %s; using defaults", guild_id)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error("Failed to parse config JSON for guild %s: %s; falling back to defaults", guild_id, exc)
        _cache_set(guild_id, merged)
        return copy.deepcopy(merged)

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
    _cache_set(guild_id, config)


async def update_guild_config(guild_id: int, **kwargs) -> dict:
    async with _get_guild_lock(guild_id):
        cfg = await get_or_create_guild_config(guild_id)
        cfg.update(kwargs)
        await set_guild_config(guild_id, cfg)
        return copy.deepcopy(cfg)


# --- Detection log / stats ---


async def log_detection(
    guild_id: int,
    domain: str,
    reason: str,
    content: str | None = None,
    attachments: list[str] | str | None = None,
) -> None:
    db = await get_db()
    if isinstance(attachments, list):
        attachments_str = json.dumps(attachments)
    else:
        attachments_str = attachments
    await db.execute(
        "INSERT INTO detection_log (guild_id, domain, reason, content, attachments) VALUES (?, ?, ?, ?, ?)",
        (str(guild_id), domain.strip(), reason, content, attachments_str),
    )


async def get_stats(guild_id: int) -> dict:
    db = await get_db()
    total_task = db.execute(
        "SELECT COUNT(*) as cnt FROM detection_log WHERE guild_id = ?",
        (str(guild_id),),
    )
    top_task = db.execute(
        "SELECT domain, COUNT(*) as cnt FROM detection_log "
        "WHERE guild_id = ? GROUP BY domain ORDER BY cnt DESC LIMIT 10",
        (str(guild_id),),
    )
    last_task = db.execute(
        "SELECT domain, reason, timestamp FROM detection_log WHERE guild_id = ? ORDER BY timestamp DESC LIMIT 1",
        (str(guild_id),),
    )
    total_rs, top_rs, last_rs = await asyncio.gather(total_task, top_task, last_task)

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
    norm_domain = domain.lower().strip()
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO custom_blocklist (domain, source) VALUES (?, ?)",
        (norm_domain, source),
    )


async def is_in_blocklist(domain: str) -> bool:
    norm_domain = domain.lower().strip()
    db = await get_db()
    rows = await db.execute(
        "SELECT 1 FROM custom_blocklist WHERE domain = ?",
        (norm_domain,),
    )
    return bool(rows.rows)


async def get_blocklist_source(domain: str) -> str | None:
    norm_domain = domain.lower().strip()
    db = await get_db()
    rows = await db.execute(
        "SELECT source FROM custom_blocklist WHERE domain = ?",
        (norm_domain,),
    )
    if rows.rows:
        return rows.rows[0][0]
    return None


async def remove_from_blocklist(domain: str) -> bool:
    norm_domain = domain.lower().strip()
    db = await get_db()
    result = await db.execute(
        "DELETE FROM custom_blocklist WHERE domain = ?",
        (norm_domain,),
    )
    return bool(result.rows_affected)
