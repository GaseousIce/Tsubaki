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


def _build_dm_embed(
    guild_name: str,
    url: str | None,
    action: str,
    dm_message: str | None,
) -> discord.Embed:
    """Build the security alert DM embed. Uses custom dm_message if provided."""
    description = (
        dm_message
        if dm_message
        else (
            f"Your account was used to send a phishing link (`{url or 'unknown'}`) "
            f"in the server **{guild_name}** and is likely compromised. "
            "Please take these security steps immediately to secure it:"
        )
    )

    embed = discord.Embed(
        title="🛡️ Account Compromised - Security Alert",
        description=description,
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow(),
    )

    _past = {"timeout": "timed out", "kick": "kicked", "ban": "banned", "warn": "warned"}.get(action, f"{action}ed")
    embed.add_field(
        name="Action Taken",
        value=f"To protect the server, your account was automatically **{_past}**.",
        inline=False,
    )

    embed.add_field(
        name="1. Reset Your Password",
        value="Your password may have been stolen — change it now to invalidate active sessions.\nhttps://discord.com/settings/account",
        inline=False,
    )
    embed.add_field(
        name="2. Enable Two-Factor Authentication (2FA)",
        value="Prevent further unauthorized access.\nhttps://discord.com/settings/account",
        inline=False,
    )
    embed.add_field(
        name="3. Review & Revoke Suspicious Apps",
        value="Check for unknown or unauthorized apps.\nSettings > Authorized Apps",
        inline=False,
    )
    embed.add_field(
        name="4. Reset Your Discord Token",
        value="Invalidate stolen session tokens.\nSettings > Advanced > Regenerate Token",
        inline=False,
    )
    embed.add_field(
        name="5. Contact Discord Support",
        value="Report the compromise and request official restoration support.\nhttps://support.discord.com/hc/en-us",
        inline=False,
    )
    embed.set_footer(text=f"Sent automatically by Tsubaki for your security | {guild_name}")
    return embed


async def is_moderator(user: discord.User | discord.Member, guild_cfg: dict) -> bool:
    if isinstance(user, discord.User) or not isinstance(user, discord.Member):
        return False
    if user.guild_permissions.administrator:
        return True
    mod_roles = guild_cfg.get("mod_roles", [])
    if any(r.id in mod_roles for r in user.roles):
        return True
    return False


class PhishingAlertView(discord.ui.View):
    def __init__(self, member: discord.Member, url: str | None, action: str, guild_cfg: dict):
        super().__init__(timeout=None)
        self.member = member
        self.url = url
        self.action = action
        self.guild_cfg = guild_cfg

        self.pardon_button = discord.ui.Button(
            label="Pardon User",
            style=discord.ButtonStyle.primary,
            custom_id=f"phish_pardon:{member.id}",
            disabled=(action != "timeout"),
        )
        self.pardon_button.callback = self.pardon_callback
        self.add_item(self.pardon_button)

        self.ban_button = discord.ui.Button(
            label="Ban User",
            style=discord.ButtonStyle.danger,
            custom_id=f"phish_ban:{member.id}",
            disabled=(action == "ban"),
        )
        self.ban_button.callback = self.ban_callback
        self.add_item(self.ban_button)

        self.allow_button = discord.ui.Button(
            label="Allow URL",
            style=discord.ButtonStyle.success,
            custom_id=f"phish_allow:{url or 'unknown'}_{member.id}",
            disabled=(not url),
        )
        self.allow_button.callback = self.allow_callback
        self.add_item(self.allow_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await is_moderator(interaction.user, self.guild_cfg):
            await interaction.response.send_message(
                "❌ You do not have permission to moderate phishing alerts.", ephemeral=True
            )
            return False
        return True

    async def pardon_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            await self.member.edit(timed_out_until=None, reason=f"Phishing pardon by {interaction.user}")

            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            embed.description += f"\n\n✅ **Pardoned by:** {interaction.user.mention}"

            self.pardon_button.disabled = True
            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send(
                f"✅ {self.member.mention} has been pardoned (timeout removed).", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ I do not have permission to edit/pardon this member.", ephemeral=True)
        except Exception as e:
            logger.exception("Pardon callback failed")
            await interaction.followup.send(f"❌ Failed to pardon user: {e}", ephemeral=True)

    async def ban_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            await self.member.ban(reason=f"Phishing manual ban by {interaction.user}")

            embed = interaction.message.embeds[0]
            embed.color = discord.Color.red()
            embed.description += f"\n\n🔨 **Banned by:** {interaction.user.mention}"

            self.ban_button.disabled = True
            self.pardon_button.disabled = True
            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send(f"🔨 {self.member.mention} has been banned.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ I do not have permission to ban this member.", ephemeral=True)
        except Exception as e:
            logger.exception("Ban callback failed")
            await interaction.followup.send(f"❌ Failed to ban user: {e}", ephemeral=True)

    async def allow_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not self.url:
            await interaction.followup.send("❌ URL is not set or unknown.", ephemeral=True)
            return

        try:
            removed = await db.remove_from_blocklist(self.url)
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.blue()

            if removed:
                embed.description += (
                    f"\n\n🔓 **URL Allowed by:** {interaction.user.mention} (Removed from custom blocklist)"
                )
            else:
                embed.description += f"\n\n🔓 **URL Allowed by:** {interaction.user.mention}"

            self.allow_button.disabled = True
            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send(f"🔓 URL `{self.url}` has been whitelisted/allowed.", ephemeral=True)
        except Exception as e:
            logger.exception("Allow URL callback failed")
            await interaction.followup.send(f"❌ Failed to allow URL: {e}", ephemeral=True)


async def handle_detection(
    message: discord.Message,
    member: discord.Member | None,
    guild_cfg: dict,
    url: str | None,
    reason: str,
) -> None:
    guild = message.guild

    if member is None:
        try:
            member = await guild.fetch_member(message.author.id)
        except discord.NotFound:
            logger.warning("User %s not found in guild %s — cannot punish", message.author.id, guild.id)
            return

    # 1. Log to DB.
    try:
        await db.log_detection(guild.id, url or "unknown", reason)
    except Exception as exc:
        logger.warning("DB log_detection failed: %s", exc)

    # 2. Delete message.
    try:
        await message.delete()
    except discord.Forbidden:
        logger.warning("Missing permission to delete message in guild %s", guild.id)
    except discord.NotFound:
        pass

    action = guild_cfg.get("action", "timeout")

    # 3. DM user.
    dm_embed = _build_dm_embed(guild.name, url, action, guild_cfg.get("dm_message"))
    try:
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        logger.info("Could not DM user %s (DMs closed)", member.id)

    # 4. Punish.
    audit_reason = f"Anti-phishing: {reason} ({url})"

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
                f"**URL:** `{url or 'unknown'}`\n"
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
                view = PhishingAlertView(member, url, action, guild_cfg)
                await ch.send(content=ping_str or None, embed=alert_embed, view=view)
            except discord.Forbidden:
                logger.warning("Cannot send alert to channel %s in guild %s", channel_id, guild.id)

    logger.info(
        "Anti-phishing action=%s url=%s reason=%s user=%s guild=%s",
        action,
        url,
        reason,
        member.id,
        guild.id,
    )
