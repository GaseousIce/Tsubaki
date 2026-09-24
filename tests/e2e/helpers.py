import discord
from simcord import Env, MemberActor

import db


async def grant_bot_permissions(env: Env, guild, **perms) -> discord.Role:
    """Grant specific permissions to the bot member in the guild."""
    bot_member = env.bot.get_guild(guild.id).get_member(env.bot.user.id)
    if perms.get("administrator"):
        permissions = discord.Permissions(administrator=True)
    else:
        permissions = discord.Permissions(**perms)
    mod_role = guild.create_role("BotMod", permissions=permissions)
    role = env.bot.get_guild(guild.id).get_role(mod_role.id)
    await bot_member.add_roles(role)
    return mod_role


def create_admin_member(env: Env, guild, name: str = "admin") -> MemberActor:
    """Create a user with Administrator permissions in the guild."""
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
    return guild.add_member(env.create_user(name), roles=[admin_role])


def create_mod_member(env: Env, guild, name: str = "mod", **perms) -> MemberActor:
    """Create a user with moderator permissions (e.g. manage_messages=True, moderate_members=True)."""
    if not perms:
        perms = {"manage_messages": True, "moderate_members": True}
    role = guild.create_role("ModRole", permissions=discord.Permissions(**perms))
    return guild.add_member(env.create_user(name), roles=[role])


def create_regular_member(env: Env, guild, name: str = "alice") -> MemberActor:
    """Create a regular user with default (unprivileged) permissions."""
    return guild.add_member(env.create_user(name))


async def set_guild_alert_channel(guild_id: int, channel_id: int) -> dict:
    """Convenience helper to set alert_channels in guild config."""
    return await db.update_guild_config(guild_id, alert_channels=[channel_id])
