import logging

import discord
from discord import app_commands

import db
from anti_phishing.config import get_guild_cfg, set_guild_cfg

logger = logging.getLogger("discord")


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


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------

antiphishing = app_commands.Group(
    name="antiphishing",
    description="Anti-phishing settings for this server",
    default_permissions=discord.Permissions(administrator=True),
    guild_only=True,
)

# ---------------------------------------------------------------------------
# Sub-groups
# ---------------------------------------------------------------------------

alert_group = app_commands.Group(name="alert", description="Manage alert channels", parent=antiphishing)
mod_role_group = app_commands.Group(name="mod-role", description="Manage mod-ping roles", parent=antiphishing)
bypass_role_group = app_commands.Group(name="bypass-role", description="Manage bypass role", parent=antiphishing)
patterns_group = app_commands.Group(name="patterns", description="Manage typosquat patterns", parent=antiphishing)


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


@antiphishing.command(name="action", description="Set the punishment action for detected phishing")
@app_commands.describe(action="Punishment to apply: timeout, kick, ban, or warn")
@app_commands.choices(
    action=[
        app_commands.Choice(name="timeout", value="timeout"),
        app_commands.Choice(name="kick", value="kick"),
        app_commands.Choice(name="ban", value="ban"),
        app_commands.Choice(name="warn", value="warn"),
    ]
)
async def cmd_action(interaction: discord.Interaction, action: str):
    await interaction.response.defer(ephemeral=True)
    try:
        await set_guild_cfg(interaction.guild_id, action=action)
        await interaction.followup.send(f"✅ Punishment action set to **{action}**.", ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing action failed: %s", exc)
        await interaction.followup.send("❌ Failed to update config.", ephemeral=True)


@antiphishing.command(name="timeout", description="Set the timeout duration (e.g. 7d, 2w, 28d)")
@app_commands.describe(duration="Duration string, e.g. 7d, 2w, 28d (max 28d)")
async def cmd_timeout(interaction: discord.Interaction, duration: str):
    await interaction.response.defer(ephemeral=True)
    from anti_phishing.actions import _parse_duration

    secs = _parse_duration(duration)
    try:
        await set_guild_cfg(interaction.guild_id, timeout_duration=secs)
        await interaction.followup.send(f"✅ Timeout duration set to **{secs}s** ({duration}).", ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing timeout failed: %s", exc)
        await interaction.followup.send("❌ Failed to update config.", ephemeral=True)


@antiphishing.command(name="enable", description="Enable anti-phishing for this server")
async def cmd_enable(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        await set_guild_cfg(interaction.guild_id, enabled=True)
        await interaction.followup.send("✅ Anti-phishing **enabled**.", ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing enable failed: %s", exc)
        await interaction.followup.send("❌ Failed to update config.", ephemeral=True)


@antiphishing.command(name="disable", description="Disable anti-phishing for this server")
async def cmd_disable(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        await set_guild_cfg(interaction.guild_id, enabled=False)
        await interaction.followup.send("⏸️ Anti-phishing **disabled**.", ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing disable failed: %s", exc)
        await interaction.followup.send("❌ Failed to update config.", ephemeral=True)


@antiphishing.command(name="status", description="Show current anti-phishing config for this server")
async def cmd_status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        cfg = await get_guild_cfg(interaction.guild_id)
    except Exception as exc:
        logger.exception("antiphishing status failed: %s", exc)
        await interaction.followup.send("❌ Failed to fetch config.", ephemeral=True)
        return

    alert_chs = ", ".join(f"<#{c}>" for c in cfg["alert_channels"]) or "none"
    mod_roles = ", ".join(f"<@&{r}>" for r in cfg["mod_roles"]) or "none"
    bypass = f"<@&{cfg['bypass_role']}>" if cfg["bypass_role"] else "none"

    embed = discord.Embed(title="Anti-Phishing Config", color=discord.Color.blurple())
    embed.add_field(name="Enabled", value="✅ yes" if cfg["enabled"] else "❌ no", inline=True)
    embed.add_field(name="Action", value=cfg["action"], inline=True)
    embed.add_field(name="Timeout", value=_format_duration(cfg["timeout_duration"]), inline=True)
    embed.add_field(name="Alert channels", value=alert_chs, inline=False)
    embed.add_field(name="Mod roles", value=mod_roles, inline=False)
    embed.add_field(name="Bypass role", value=bypass, inline=False)
    embed.add_field(name="Custom DM", value=cfg.get("dm_message") or "default", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


@antiphishing.command(name="stats", description="Show detection stats for this server")
async def cmd_stats(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        stats = await db.get_stats(interaction.guild_id)
    except Exception as exc:
        logger.exception("antiphishing stats failed: %s", exc)
        await interaction.followup.send("❌ Failed to fetch stats.", ephemeral=True)
        return

    embed = discord.Embed(title="Anti-Phishing Stats", color=discord.Color.blurple())
    embed.add_field(name="Total detections", value=str(stats["total"]), inline=False)

    if stats["top"]:
        top_str = "\n".join(f"`{e['domain']}` — {e['count']}x" for e in stats["top"])
        embed.add_field(name="Top blocked domains", value=top_str, inline=False)

    if stats["last"]:
        last = stats["last"]
        embed.add_field(
            name="Last detection",
            value=f"`{last['domain']}` ({last['reason']}) at {last['timestamp']}",
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@antiphishing.command(name="dm-message", description="Set a custom DM recovery message (omit to reset to default)")
@app_commands.describe(text="Custom DM text; leave blank to reset to default")
async def cmd_dm_message(interaction: discord.Interaction, text: str = ""):
    await interaction.response.defer(ephemeral=True)
    value = text.strip() or None
    try:
        await set_guild_cfg(interaction.guild_id, dm_message=value)
        if value:
            await interaction.followup.send("✅ Custom DM message set.", ephemeral=True)
        else:
            await interaction.followup.send("✅ DM message reset to default.", ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing dm-message failed: %s", exc)
        await interaction.followup.send("❌ Failed to update config.", ephemeral=True)


# ---------------------------------------------------------------------------
# Alert channel commands
# ---------------------------------------------------------------------------


@alert_group.command(name="add", description="Add an alert channel")
@app_commands.describe(channel="Text channel to post phishing alerts in")
async def alert_add(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    try:
        cfg = await get_guild_cfg(interaction.guild_id)
        channels = cfg["alert_channels"]
        if channel.id not in channels:
            channels.append(channel.id)
            await set_guild_cfg(interaction.guild_id, alert_channels=channels)
        await interaction.followup.send(f"✅ {channel.mention} added to alert channels.", ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing alert add failed: %s", exc)
        await interaction.followup.send("❌ Failed to update config.", ephemeral=True)


@alert_group.command(name="remove", description="Remove an alert channel")
@app_commands.describe(channel="Channel to remove from alerts")
async def alert_remove(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    try:
        cfg = await get_guild_cfg(interaction.guild_id)
        channels = cfg["alert_channels"]
        if channel.id in channels:
            channels.remove(channel.id)
            await set_guild_cfg(interaction.guild_id, alert_channels=channels)
        await interaction.followup.send(f"✅ {channel.mention} removed from alert channels.", ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing alert remove failed: %s", exc)
        await interaction.followup.send("❌ Failed to update config.", ephemeral=True)


@alert_group.command(name="list", description="List current alert channels")
async def alert_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        cfg = await get_guild_cfg(interaction.guild_id)
        channels = cfg["alert_channels"]
        if channels:
            value = "\n".join(f"<#{c}>" for c in channels)
        else:
            value = "No alert channels configured."
        embed = discord.Embed(title="Alert Channels", description=value, color=discord.Color.blurple())
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing alert list failed: %s", exc)
        await interaction.followup.send("❌ Failed to fetch config.", ephemeral=True)


# ---------------------------------------------------------------------------
# Mod role commands
# ---------------------------------------------------------------------------


@mod_role_group.command(name="add", description="Add a role to the alert ping list")
@app_commands.describe(role="Role to ping on detections")
async def mod_role_add(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(ephemeral=True)
    try:
        cfg = await get_guild_cfg(interaction.guild_id)
        roles = cfg["mod_roles"]
        if role.id not in roles:
            roles.append(role.id)
            await set_guild_cfg(interaction.guild_id, mod_roles=roles)
        await interaction.followup.send(f"✅ {role.mention} added to mod-role ping list.", ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing mod-role add failed: %s", exc)
        await interaction.followup.send("❌ Failed to update config.", ephemeral=True)


@mod_role_group.command(name="remove", description="Remove a role from the alert ping list")
@app_commands.describe(role="Role to remove")
async def mod_role_remove(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(ephemeral=True)
    try:
        cfg = await get_guild_cfg(interaction.guild_id)
        roles = cfg["mod_roles"]
        if role.id in roles:
            roles.remove(role.id)
            await set_guild_cfg(interaction.guild_id, mod_roles=roles)
        await interaction.followup.send(f"✅ {role.mention} removed from mod-role ping list.", ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing mod-role remove failed: %s", exc)
        await interaction.followup.send("❌ Failed to update config.", ephemeral=True)


@mod_role_group.command(name="list", description="List mod roles")
async def mod_role_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        cfg = await get_guild_cfg(interaction.guild_id)
        roles = cfg["mod_roles"]
        value = "\n".join(f"<@&{r}>" for r in roles) if roles else "No mod roles configured."
        embed = discord.Embed(title="Mod Roles", description=value, color=discord.Color.blurple())
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing mod-role list failed: %s", exc)
        await interaction.followup.send("❌ Failed to fetch config.", ephemeral=True)


# ---------------------------------------------------------------------------
# Bypass role commands
# ---------------------------------------------------------------------------


@bypass_role_group.command(name="set", description="Set a role that bypasses all phishing checks")
@app_commands.describe(role="Role to exempt from checks")
async def bypass_role_set(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(ephemeral=True)
    try:
        await set_guild_cfg(interaction.guild_id, bypass_role=role.id)
        await interaction.followup.send(f"✅ {role.mention} set as bypass role.", ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing bypass-role set failed: %s", exc)
        await interaction.followup.send("❌ Failed to update config.", ephemeral=True)


@bypass_role_group.command(name="remove", description="Remove the bypass role")
async def bypass_role_remove(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        await set_guild_cfg(interaction.guild_id, bypass_role=0)
        await interaction.followup.send("✅ Bypass role removed.", ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing bypass-role remove failed: %s", exc)
        await interaction.followup.send("❌ Failed to update config.", ephemeral=True)


@bypass_role_group.command(name="list", description="Show current bypass role")
async def bypass_role_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        cfg = await get_guild_cfg(interaction.guild_id)
        bypass = cfg.get("bypass_role", 0)
        value = f"<@&{bypass}>" if bypass else "No bypass role set."
        embed = discord.Embed(title="Bypass Role", description=value, color=discord.Color.blurple())
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing bypass-role list failed: %s", exc)
        await interaction.followup.send("❌ Failed to fetch config.", ephemeral=True)


# ---------------------------------------------------------------------------
# Typosquat pattern commands
# ---------------------------------------------------------------------------


@patterns_group.command(name="add", description="Add a typosquat pattern (e.g. discord-nitro)")
@app_commands.describe(text="Pattern substring to detect in domains")
async def patterns_add(interaction: discord.Interaction, text: str):
    await interaction.response.defer(ephemeral=True)
    clean_text = text.strip().lower()
    if len(clean_text) < 3:
        await interaction.followup.send("❌ Pattern must be at least 3 characters long.", ephemeral=True)
        return

    overly_generic = {
        "com",
        "net",
        "org",
        "info",
        "xyz",
        "ru",
        "edu",
        "gov",
        "co",
        "io",
        "uk",
        "de",
        "http",
        "https",
        "www",
    }
    if clean_text in overly_generic:
        await interaction.followup.send(
            f"❌ Pattern `{clean_text}` is too generic and cannot be blocked.",
            ephemeral=True,
        )
        return

    try:
        await db.add_pattern(clean_text)
        await interaction.followup.send(f"✅ Pattern `{clean_text}` added.", ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing patterns add failed: %s", exc)
        await interaction.followup.send("❌ Failed to add pattern.", ephemeral=True)


@patterns_group.command(name="remove", description="Remove a typosquat pattern")
@app_commands.describe(text="Pattern to remove")
async def patterns_remove(interaction: discord.Interaction, text: str):
    await interaction.response.defer(ephemeral=True)
    try:
        removed = await db.remove_pattern(text.strip().lower())
        if removed:
            await interaction.followup.send(f"✅ Pattern `{text}` removed.", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️ Pattern `{text}` not found.", ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing patterns remove failed: %s", exc)
        await interaction.followup.send("❌ Failed to remove pattern.", ephemeral=True)


@patterns_group.command(name="list", description="List all typosquat patterns")
async def patterns_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        patterns = await db.get_patterns()
        value = "\n".join(f"`{p}`" for p in patterns) if patterns else "No patterns configured."
        embed = discord.Embed(title="Typosquat Patterns", description=value, color=discord.Color.blurple())
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing patterns list failed: %s", exc)
        await interaction.followup.send("❌ Failed to fetch patterns.", ephemeral=True)
