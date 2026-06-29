import logging
import os
from datetime import time

import discord
from discord.ext import tasks

logger = logging.getLogger("discord")


def setup(bot):
    @bot.tree.command(name="clear", description="Clear all messages in this channel")
    async def clear(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.channel.purge()
            await interaction.followup.send("Channel cleared.", ephemeral=True)
            logger.info(
                "Channel %s manually cleared by %s",
                interaction.channel.id,
                interaction.user,
            )
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to delete messages here.", ephemeral=True)
        except discord.HTTPException as e:
            logger.error("Manual clear failed in %s: %s", interaction.channel.id, e)
            await interaction.followup.send("Failed to clear the channel.", ephemeral=True)

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
            await channel.purge()
            logger.info("Cleared channel %s", channel_id)
        except discord.Forbidden:
            logger.error("Missing permissions to clear channel %s", channel_id)
        except discord.HTTPException as e:
            logger.error("Failed to clear channel %s: %s", channel_id, e)

    @daily_clear.before_loop
    async def before_daily_clear():
        await bot.wait_until_ready()

    daily_clear.start()
