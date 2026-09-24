import collections.abc
import inspect
import logging
import os
from datetime import time, timezone

import discord
from discord import app_commands
from discord.ext import tasks

logger = logging.getLogger("discord")


async def purge_channel(
    channel: discord.abc.Messageable,
    ctx_info: str = "",
    limit: int | None = 100,
    check: collections.abc.Callable[[discord.Message], bool] | None = None,
) -> tuple[int | None, str | None]:
    """Purge messages in channel.

    Returns:
        tuple[int | None, str | None]: (count, None) on success,
        (None, "unsupported") if channel does not support purge,
        (None, "forbidden") if bot lacks permissions,
        (None, f"API error: {e}") on HTTPException.
    """
    if not hasattr(channel, "purge"):
        logger.error("Channel %s does not support purge", getattr(channel, "id", None))
        return (None, "unsupported")

    try:
        kwargs = {"limit": limit}
        if check is not None:
            kwargs["check"] = check
        deleted = await channel.purge(**kwargs)
        count = len(deleted)
        logger.info("Cleared %d messages in channel %s %s", count, getattr(channel, "id", ""), ctx_info)
        return (count, None)
    except discord.Forbidden:
        logger.error("Missing permissions to clear channel %s", getattr(channel, "id", ""))
        return (None, "forbidden")
    except discord.HTTPException as e:
        logger.error("Failed to clear channel %s: %s", getattr(channel, "id", ""), e)
        return (None, f"API error: {e}")


def setup(bot):
    @bot.tree.command(name="clear", description="Clear messages in this channel with optional filters")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(
        limit="Number of messages to clear (1-100, default: 100)",
        user="Only clear messages from this user",
        bots_only="Only clear messages sent by bots",
    )
    async def clear(
        interaction: discord.Interaction,
        limit: app_commands.Range[int, 1, 100] = 100,
        user: discord.Member | None = None,
        bots_only: bool | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        if not hasattr(interaction.channel, "purge"):
            await interaction.followup.send("❌ This channel does not support message purging.", ephemeral=True)
            return

        if limit is None:
            limit = 100
        elif limit < 1 or limit > 100:
            await interaction.followup.send("❌ Limit must be between 1 and 100 messages.", ephemeral=True)
            return

        def purge_check(message: discord.Message) -> bool:
            if user is not None and message.author.id != user.id:
                return False
            if bots_only is not None and message.author.bot != bots_only:
                return False
            return True

        res = await purge_channel(
            interaction.channel,
            ctx_info=f"by {interaction.user}",
            limit=limit,
            check=purge_check if (user is not None or bots_only is not None) else None,
        )

        if isinstance(res, tuple):
            count, err = res
        elif res is None:
            count, err = None, "forbidden"
        else:
            count, err = res, None

        if count is not None:
            filter_desc = []
            if user:
                filter_desc.append(f"from {user.mention}")
            if bots_only:
                filter_desc.append("from bots")
            filter_str = f" ({', '.join(filter_desc)})" if filter_desc else ""
            await interaction.followup.send(
                f"✅ Successfully cleared **{count}** messages{filter_str}.", ephemeral=True
            )
        elif err == "forbidden":
            await interaction.followup.send("❌ I don't have permission to delete messages here.", ephemeral=True)
        elif err == "unsupported":
            await interaction.followup.send("❌ This channel does not support message purging.", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Failed to clear messages: {err}", ephemeral=True)

    @clear.error
    async def clear_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        target = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        range_err = getattr(app_commands, "RangeError", None)
        try:
            if isinstance(error, app_commands.MissingPermissions):
                await target("❌ You need Manage Messages permission to use /clear.", ephemeral=True)
            elif range_err is not None and isinstance(error, range_err):
                await target("❌ Limit must be between 1 and 100 messages.", ephemeral=True)
            elif isinstance(error, app_commands.CheckFailure):
                await target("❌ You do not have permission to run this command.", ephemeral=True)
            else:
                logger.error("Unhandled error in /clear: %s", error)
                await target("An error occurred.", ephemeral=True)
        except discord.HTTPException:
            pass

    channel_id = os.getenv("CLEAR_CHANNEL_ID")
    if not channel_id:
        logger.warning("CLEAR_CHANNEL_ID not set: daily clear disabled")
        return

    try:
        channel_id = int(channel_id)
    except ValueError:
        logger.error("CLEAR_CHANNEL_ID is not a valid snowflake")
        return

    @tasks.loop(time=time(hour=3, tzinfo=timezone.utc))
    async def daily_clear():
        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            if channel:
                if not hasattr(channel, "purge"):
                    logger.error("Daily clear channel %s does not support purge", channel_id)
                    return
                res = await purge_channel(channel, "(daily)", limit=100)
                if isinstance(res, tuple):
                    _count, err = res
                elif res is None:
                    _count, err = None, "forbidden"
                else:
                    _count, err = res, None
                if err:
                    logger.error("Daily clear failed in channel %s: %s", channel_id, err)
            else:
                logger.error("Daily clear channel %s not found", channel_id)
        except Exception as e:
            logger.exception("Failed to run daily channel clear: %s", e)

    @daily_clear.error
    async def daily_clear_error(error: Exception):
        logger.exception("Unhandled exception in daily_clear task loop: %s", error)

    @daily_clear.before_loop
    async def before_daily_clear():
        try:
            wait_fn = getattr(bot, "wait_until_ready", None)
            if callable(wait_fn):
                res = wait_fn()
                if inspect.isawaitable(res):
                    await res
        except Exception as e:
            logger.warning("Error waiting for bot ready in daily_clear: %s", e)

    daily_clear.start()
