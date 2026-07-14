import logging

import discord
from discord import app_commands

from groq_service import ask_tsubaki

logger = logging.getLogger("discord")


def setup(bot, groq_model: str = "openai/gpt-oss-120b") -> None:
    """Register /hello, /ping, and /ask commands on the bot.

    The bot must have an ``ai_service`` attribute (set to an ``AsyncGroq``
    client or ``None``) before /ask is invoked.  Setting it to ``None``
    disables the command gracefully.
    """

    @bot.tree.command(name="hello", description="Say hello to Tsubaki")
    async def hello(interaction: discord.Interaction):
        await interaction.response.send_message("hello there! :3")

    @bot.tree.command(name="ping", description="Check if the bot is online")
    async def ping(interaction: discord.Interaction):
        latency_ms = round(bot.latency * 1000)
        await interaction.response.send_message(f"Pong! {latency_ms} ms")

    @bot.tree.command(name="ask", description="Ask Tsubaki anything")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
    async def ask(interaction: discord.Interaction, question: str):
        ai_service = getattr(bot, "ai_service", None)
        if ai_service is None:
            await interaction.response.send_message("The Groq API key is not configured yet.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        try:
            async with interaction.channel.typing():
                answer = await ask_tsubaki(ai_service, question, model=groq_model)
        except Exception:
            logger.exception("Groq request for /ask failed")
            await interaction.followup.send(
                "Uuu... (╥﹏╥) My brainwaves got all tangled up! I couldn't reach my thoughts right now. "
                "Please try asking me again in a bit, okay? (｡>﹏<｡)"
            )
            return

        if len(answer) > 2000:
            answer = f"{answer[:1997]}..."

        await interaction.followup.send(answer)

    @ask.error
    async def ask_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        try:
            if isinstance(error, app_commands.CommandOnCooldown):
                await interaction.response.send_message(
                    f"H-Hey! Don't spam me! ( ｀皿´) Please wait {error.retry_after:.1f}s before asking again, baka!",
                    ephemeral=True,
                )
            else:
                logger.error("Unhandled error in /ask command: %s", error)
                target = (
                    interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
                )
                await target("An error occurred.", ephemeral=True)
        except discord.HTTPException:
            pass
