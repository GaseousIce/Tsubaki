import logging

import discord
from discord import app_commands

import db
from anti_phishing import domain

logger = logging.getLogger("discord")

_ACTION_PERMS = {
    "timeout": ("moderate_members", "Moderate Members"),
    "kick": ("kick_members", "Kick Members"),
    "ban": ("ban_members", "Ban Members"),
    "warn": (None, None),
}


async def _check_db_health() -> bool:
    try:
        client = await db.get_db()
        await client.execute("SELECT 1")
        return True
    except Exception:
        return False


def _check_role_position(guild: discord.Guild) -> tuple[str, bool]:
    me = guild.me
    if not me or not me.top_role:
        return ("Could not determine bot role position.", False)
    total = len(guild.roles)
    rank = total - me.top_role.position
    if rank <= 3:
        return (
            f"⚠️ Bot role is #{rank} of {total} — drag it above all others (except admin) for proper moderation.",
            False,
        )
    return (f"✅ Bot role is #{rank} of {total} — plenty of authority.", True)


def _check_guild_permissions(me: discord.Member) -> list[tuple[str, bool]]:
    checks = [
        ("moderate_members", "Moderate Members"),
        ("kick_members", "Kick Members"),
        ("ban_members", "Ban Members"),
        ("manage_messages", "Manage Messages"),
        ("manage_roles", "Manage Roles"),
    ]
    return [(label, getattr(me.guild_permissions, perm, False)) for perm, label in checks]


def _check_action_readiness(me: discord.Member, action: str) -> tuple[str, bool]:
    attr, label = _ACTION_PERMS.get(action, (None, None))
    if attr is None:
        return (f"{action.capitalize()} (no guild permission needed)", True)
    has = getattr(me.guild_permissions, attr, False)
    return (f"{action.capitalize()} {'✅' if has else '❌'} — requires **{label}**", has)


def _check_alert_channels(guild: discord.Guild, channel_ids: list[int]) -> list[tuple[str, bool]]:
    results = []
    me = guild.me
    if not me:
        return []
    for cid in channel_ids:
        ch = guild.get_channel(cid)
        if not ch:
            results.append((f"<#{cid}> ❓ Deleted or inaccessible", False))
            continue
        perms = ch.permissions_for(me)
        ok = perms.view_channel and perms.send_messages and perms.embed_links
        if ok:
            results.append((f"{ch.mention} ✅", True))
        else:
            missing = []
            if not perms.view_channel:
                missing.append("View Channel")
            if not perms.send_messages:
                missing.append("Send Messages")
            if not perms.embed_links:
                missing.append("Embed Links")
            results.append((f"{ch.mention} ❌ missing {', '.join(missing)}", False))
    return results


def _build_setup_embed(
    guild: discord.Guild,
    cfg: dict,
    db_ok: bool,
    blacklist_count: int,
) -> discord.Embed:
    me = guild.me
    embed = discord.Embed(
        title=f"🛡️ Tsubaki Setup — {guild.name}",
        color=discord.Color.blurple(),
    )

    role_msg, _ = _check_role_position(guild)
    embed.add_field(name="🤖 Bot Role", value=role_msg, inline=False)

    if me:
        perm_lines = "\n".join(f"{'✅' if ok else '❌'} {label}" for label, ok in _check_guild_permissions(me))
        embed.add_field(name="🔧 Guild Permissions", value=perm_lines, inline=False)

    action = cfg.get("action", "timeout")
    action_msg, _ = _check_action_readiness(me, action) if me else (action.capitalize(), False)
    embed.add_field(name="⚡ Action", value=action_msg, inline=True)

    enabled = "🟢 Enabled" if cfg.get("enabled", True) else "🔴 Disabled"
    embed.add_field(name="Status", value=enabled, inline=True)
    embed.add_field(name="Timeout Duration", value=_format_duration(cfg.get("timeout_duration", 604800)), inline=True)

    ch_results = _check_alert_channels(guild, cfg.get("alert_channels", []))
    ch_val = "\n".join(r[0] for r in ch_results) if ch_results else "none configured"
    embed.add_field(name=f"📢 Alert Channels ({len(ch_results)})", value=ch_val, inline=False)

    db_icon = "✅" if db_ok else "❌"
    embed.add_field(name="💾 Database", value=f"{db_icon} {'connected' if db_ok else 'unreachable'}", inline=True)

    bl_icon = "✅" if blacklist_count else "⚠️"
    embed.add_field(
        name="📊 Blacklist",
        value=f"{bl_icon} {blacklist_count:,} domains loaded" if blacklist_count else "⚠️ none loaded — check network",
        inline=True,
    )

    return embed


def _format_duration(seconds: int) -> str:
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if not days and minutes:
        parts.append(f"{minutes}m")
    if not days and not hours and secs:
        parts.append(f"{secs}s")
    return " ".join(parts) if parts else "0s"


def setup(bot):
    @bot.tree.command(name="setup", description="Run a full health, permissions, and configuration check")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def setup_cmd(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            db_ok = await _check_db_health()
            cfg = await db.get_guild_config(interaction.guild_id)
            blacklist_count = len(domain.official)
            embed = _build_setup_embed(interaction.guild, cfg, db_ok, blacklist_count)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            logger.exception("setup command failed")
            await interaction.followup.send(f"❌ Setup check failed: {exc}", ephemeral=True)
