import logging
import os
from datetime import time

import discord
from discord import app_commands
from discord.ext import tasks

logger = logging.getLogger("discord")


async def purge_channel(channel: discord.abc.Messageable, ctx_info: str = "") -> bool:
    try:
        await channel.purge()
        logger.info("Cleared channel %s %s", channel.id, ctx_info)
        return True
    except discord.Forbidden:
        logger.error("Missing permissions to clear channel %s", channel.id)
        return False
    except discord.HTTPException as e:
        logger.error("Failed to clear channel %s: %s", channel.id, e)
        return False


def setup(bot):
    @bot.tree.command(name="clear", description="Clear all messages in this channel")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ok = await purge_channel(interaction.channel, f"by {interaction.user}")
        if ok:
            await interaction.followup.send("Channel cleared.", ephemeral=True)
        else:
            await interaction.followup.send("I don't have permission to delete messages here.", ephemeral=True)

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
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        await purge_channel(channel, "(daily)")

    @daily_clear.before_loop
    async def before_daily_clear():
        await bot.wait_until_ready()

    daily_clear.start()
