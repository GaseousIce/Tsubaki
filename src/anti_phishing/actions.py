import datetime
import logging

import discord

import db

logger = logging.getLogger("discord")

_PARSE_UNITS = {"d": 86400, "w": 604800}
_MAX_TIMEOUT_SECONDS = 2419200  # 28 days


def _parse_duration(duration: str) -> int:
    """Parse a duration string like '7d', '2w', '28d' into seconds. Clamps to 28d max."""
    duration = duration.strip().lower()
    for suffix, multiplier in _PARSE_UNITS.items():
        if duration.endswith(suffix):
            try:
                value = int(duration[: -len(suffix)])
                return min(value * multiplier, _MAX_TIMEOUT_SECONDS)
            except ValueError:
                pass
    # Fallback: try plain integer seconds.
    try:
        return min(int(duration), _MAX_TIMEOUT_SECONDS)
    except ValueError:
        return 604800  # default 7d


def _build_dm_embed(dm_message: str | None) -> discord.Embed:
    """Build the security alert DM embed. Uses custom dm_message if provided."""
    description = (
        dm_message if dm_message else "You may have interacted with a phishing link. Take these steps immediately:"
    )
    embed = discord.Embed(
        title="Security Alert",
        description=description,
        color=discord.Color.red(),
    )
    embed.add_field(name="1. Reset Your Password", value="https://discord.com/settings/account", inline=False)
    embed.add_field(
        name="2. Enable Two-Factor Authentication",
        value="https://discord.com/settings/account",
        inline=False,
    )
    embed.add_field(name="3. Revoke Authorized Apps", value="Settings > Authorized Apps", inline=False)
    embed.add_field(
        name="4. Reset Your Discord Token",
        value="Settings > Advanced > Regenerate Token",
        inline=False,
    )
    embed.add_field(
        name="5. Contact Discord Support",
        value="https://support.discord.com/hc/en-us",
        inline=False,
    )
    embed.set_footer(text="If you didn't click anything, you can ignore this message.")
    return embed


async def handle_detection(
    message: discord.Message,
    member: discord.Member | None,
    guild_cfg: dict,
    domain: str | None,
    reason: str,
) -> None:
    """
    Full detection pipeline:
    1. Log to DB
    2. Delete message
    3. DM user
    4. Punish
    5. Alert mod channels
    6. Log to file
    """
    guild = message.guild

    if member is None:
        try:
            member = await guild.fetch_member(message.author.id)
        except discord.NotFound:
            logger.warning("User %s not found in guild %s — cannot punish", message.author.id, guild.id)
            return

    # 1. Log to DB.
    try:
        await db.log_detection(guild.id, domain or "unknown", reason)
    except Exception as exc:
        logger.warning("DB log_detection failed: %s", exc)

    # 2. Delete message.
    try:
        await message.delete()
    except discord.Forbidden:
        logger.warning("Missing permission to delete message in guild %s", guild.id)
    except discord.NotFound:
        pass

    # 3. DM user.
    dm_embed = _build_dm_embed(guild_cfg.get("dm_message"))
    try:
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        logger.info("Could not DM user %s (DMs closed)", member.id)

    # 4. Punish.
    action = guild_cfg.get("action", "timeout")
    audit_reason = f"Anti-phishing: {reason} ({domain})"

    if action == "timeout":
        duration_secs = guild_cfg.get("timeout_duration", 604800)
        until = discord.utils.utcnow() + datetime.timedelta(seconds=duration_secs)
        try:
            await member.timeout(until, reason=audit_reason)
        except discord.Forbidden:
            logger.warning("Missing permission to timeout %s in guild %s", member.id, guild.id)

    elif action == "kick":
        try:
            await member.kick(reason=audit_reason)
        except discord.Forbidden:
            logger.warning("Missing permission to kick %s in guild %s", member.id, guild.id)

    elif action == "ban":
        try:
            await member.ban(reason=audit_reason)
        except discord.Forbidden:
            logger.warning("Missing permission to ban %s in guild %s", member.id, guild.id)

    elif action == "warn":
        # DM only — no server action.
        pass

    # 5. Alert mod channels.
    alert_channels: list[int] = guild_cfg.get("alert_channels", [])
    mod_roles: list[int] = guild_cfg.get("mod_roles", [])

    if alert_channels:
        ping_str = " ".join(f"<@&{r}>" for r in mod_roles) if mod_roles else ""
        alert_embed = discord.Embed(
            title="⚠️ Phishing Detected",
            description=(
                f"**User:** {member.mention} (`{member}`, ID: `{member.id}`)\n"
                f"**Domain:** `{domain or 'unknown'}`\n"
                f"**Reason:** `{reason}`\n"
                f"**Action:** `{action}`\n"
                f"**Channel:** {message.channel.mention}"
            ),
            color=discord.Color.orange(),
        )
        alert_embed.set_footer(text=f"Guild: {guild.name}")

        for channel_id in alert_channels:
            ch = guild.get_channel(channel_id)
            if ch is None:
                continue
            try:
                await ch.send(content=ping_str or None, embed=alert_embed)
            except discord.Forbidden:
                logger.warning("Cannot send alert to channel %s in guild %s", channel_id, guild.id)

    logger.info(
        "Anti-phishing action=%s domain=%s reason=%s user=%s guild=%s",
        action,
        domain,
        reason,
        member.id,
        guild.id,
    )
