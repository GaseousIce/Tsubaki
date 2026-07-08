import logging
import os
from datetime import time

import discord
from discord import app_commands
from discord.ext import tasks

logger = logging.getLogger("discord")


async def purge_channel(
    channel: discord.abc.Messageable,
    ctx_info: str = "",
    limit: int | None = None,
    check=None,
) -> int | None:
    try:
        deleted = await channel.purge(limit=limit, check=check)
        count = len(deleted)
        logger.info("Cleared %d messages in channel %s %s", count, channel.id, ctx_info)
        return count
    except discord.Forbidden:
        logger.error("Missing permissions to clear channel %s", channel.id)
        return None
    except discord.HTTPException as e:
        logger.error("Failed to clear channel %s: %s", channel.id, e)
        return None


def setup(bot):
    @bot.tree.command(name="clear", description="Clear messages in this channel with optional filters")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(
        limit="Number of messages to clear (default: clear all)",
        user="Only clear messages from this user",
        bots_only="Only clear messages sent by bots",
    )
    async def clear(
        interaction: discord.Interaction,
        limit: int | None = None,
        user: discord.Member | None = None,
        bots_only: bool | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        def purge_check(message: discord.Message) -> bool:
            if user is not None and message.author.id != user.id:
                return False
            if bots_only is not None and message.author.bot != bots_only:
                return False
            return True

        count = await purge_channel(
            interaction.channel,
            ctx_info=f"by {interaction.user}",
            limit=limit,
            check=purge_check if (user is not None or bots_only is not None) else None,
        )

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
        else:
            await interaction.followup.send("❌ I don't have permission to delete messages here.", ephemeral=True)

    channel_id = os.getenv("CLEAR_CHANNEL_ID")
    if not channel_id:
        logger.warning("CLEAR_CHANNEL_ID not set: daily clear disabled")
        return

    try:
        channel_id = int(channel_id)
    except ValueError:
        logger.error("CLEAR_CHANNEL_ID is not a valid snowflake")
        return

    @tasks.loop(time=time(hour=3))
    async def daily_clear():
        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            if channel:
                await purge_channel(channel, "(daily)")
            else:
                logger.error("Daily clear channel %s not found", channel_id)
        except Exception as e:
            logger.exception("Failed to run daily channel clear: %s", e)

    @daily_clear.before_loop
    async def before_daily_clear():
        await bot.wait_until_ready()

    daily_clear.start()
