import logging

import discord
from discord import app_commands

import db

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


def _build_settings_embed(guild: discord.Guild, cfg: dict) -> discord.Embed:
    alert_chs = ", ".join(f"<#{c}>" for c in cfg["alert_channels"]) or "none"
    mod_roles = ", ".join(f"<@&{r}>" for r in cfg["mod_roles"]) or "none"
    bypass = f"<@&{cfg['bypass_role']}>" if cfg["bypass_role"] else "none"

    embed = discord.Embed(title=f"🛡️ Anti-Phishing Settings — {guild.name}", color=discord.Color.blurple())
    embed.add_field(name="Status", value="🟢 Enabled" if cfg["enabled"] else "🔴 Disabled", inline=True)
    embed.add_field(name="Action", value=cfg["action"].capitalize(), inline=True)
    embed.add_field(name="Timeout Duration", value=_format_duration(cfg["timeout_duration"]), inline=True)
    embed.add_field(name="Alert Channels", value=alert_chs, inline=False)
    embed.add_field(name="Mod Roles", value=mod_roles, inline=False)
    embed.add_field(name="Bypass Role", value=bypass, inline=False)

    dm_msg = cfg.get("dm_message")
    if dm_msg:
        if len(dm_msg) > 100:
            dm_msg = f"{dm_msg[:97]}..."
    else:
        dm_msg = "Default"
    embed.add_field(name="Custom DM Message", value=dm_msg, inline=False)

    embed.set_footer(text="Configure settings via /antiphishing configure")
    return embed


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
# Top-level commands
# ---------------------------------------------------------------------------


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


@antiphishing.command(name="settings", description="Show anti-phishing settings dashboard")
async def cmd_settings(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        cfg = await db.get_guild_config(interaction.guild_id)
        embed = _build_settings_embed(interaction.guild, cfg)
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing settings failed: %s", exc)
        await interaction.followup.send("❌ Failed to show settings.", ephemeral=True)


@antiphishing.command(name="configure", description="Configure anti-phishing settings")
@app_commands.describe(
    enabled="Enable or disable anti-phishing",
    action="Punishment action: timeout, kick, ban, warn",
    timeout_duration="Timeout duration (e.g. 7d, 28d, or seconds)",
    alert_channel="Text channel to send detection alerts to",
    mod_role="Role to ping when a detection alert is sent",
    bypass_role="Role that bypasses anti-phishing checks (use @everyone to reset/none)",
    dm_message="Custom DM message for punished users (set to 'default' to reset)",
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="Timeout", value="timeout"),
        app_commands.Choice(name="Kick", value="kick"),
        app_commands.Choice(name="Ban", value="ban"),
        app_commands.Choice(name="Warn", value="warn"),
    ]
)
async def cmd_configure(
    interaction: discord.Interaction,
    enabled: bool | None = None,
    action: str | None = None,
    timeout_duration: str | None = None,
    alert_channel: discord.TextChannel | None = None,
    mod_role: discord.Role | None = None,
    bypass_role: discord.Role | None = None,
    dm_message: str | None = None,
):
    await interaction.response.defer(ephemeral=True)
    try:
        updates = {}
        if enabled is not None:
            updates["enabled"] = enabled
        if action is not None:
            updates["action"] = action
        if timeout_duration is not None:
            from anti_phishing.actions import _parse_duration

            updates["timeout_duration"] = _parse_duration(timeout_duration)
        if alert_channel is not None:
            updates["alert_channels"] = [alert_channel.id]
        if mod_role is not None:
            updates["mod_roles"] = [mod_role.id]
        if bypass_role is not None:
            if bypass_role.is_default():
                updates["bypass_role"] = 0
            else:
                updates["bypass_role"] = bypass_role.id
        if dm_message is not None:
            updates["dm_message"] = None if dm_message.lower() == "default" else dm_message

        if updates:
            await db.update_guild_config(interaction.guild_id, **updates)
            await interaction.followup.send("✅ Settings successfully updated!", ephemeral=True)
        else:
            await interaction.followup.send("ℹ️ No settings specified to update.", ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing configure failed: %s", exc)
        await interaction.followup.send("❌ Failed to update settings.", ephemeral=True)
