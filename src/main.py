import logging
import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("DISCORD_TOKEN")

Path("logs").mkdir(exist_ok=True)
handler = logging.FileHandler(filename="logs/logs.log", encoding="utf-8", mode="w")
handler.setFormatter(
    logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
)
logger = logging.getLogger("discord")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)


@bot.event
async def setup_hook():
    # Sync slash commands with Discord on startup.
    synced = await bot.tree.sync()
    logger.info("Synced %s slash command(s)", len(synced))


@bot.event
async def on_ready():
    print(f"{bot.user.name} has connected to Discord!")


@bot.tree.command(name="hello", description="Say hello to Tsubaki")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message("hello there! :3")


@bot.tree.command(name="ping", description="Check if the bot is online")
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! {latency_ms} ms")


bot.run(token, log_handler=handler, log_level=logging.DEBUG)
