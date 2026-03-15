import logging
import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("DISCORD_TOKEN")

Path("logs").mkdir(exist_ok=True)
handler = logging.FileHandler(filename="logs/automod.log", encoding="utf-8", mode="w")
handler.setFormatter(
    logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
)
logger = logging.getLogger("discord")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"{bot.user.name} has connected to Discord!")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if "hello" in message.content.lower():
        await message.reply("hello there!", mention_author=False)


bot.run(token, log_handler=handler, log_level=logging.DEBUG)
