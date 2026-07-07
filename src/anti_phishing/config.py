import db

_DEFAULT_CONFIG = {
    "enabled": True,
    "action": "timeout",
    "timeout_duration": 604800,
    "alert_channels": [],
    "mod_roles": [],
    "dm_message": None,
    "bypass_role": 0,
}


async def get_guild_cfg(guild_id: int) -> dict:
    """Return per-guild anti-phishing config merged with defaults."""
    return await db.get_guild_config(guild_id, _DEFAULT_CONFIG)


async def set_guild_cfg(guild_id: int, **kwargs) -> dict:
    """Merge kwargs into the guild's stored config and persist. Returns new config."""
    cfg = await get_guild_cfg(guild_id)
    cfg.update(kwargs)
    await db.set_guild_config(guild_id, cfg)
    return cfg
