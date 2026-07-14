import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Thread

import discord
from discord.ext import commands
from dotenv import load_dotenv

from anti_phishing import fetch_official_blacklist
from anti_phishing import setup as setup_anti_phishing
from channel_clear import setup as setup_channel_clear
from commands import setup as setup_commands
from config import load_config
from db import migrate
from groq_service import get_groq_client
from setup import setup as setup_setup

load_dotenv()
token = os.getenv("DISCORD_TOKEN")
config = load_config()

if not token:
    raise ValueError("DISCORD_TOKEN is not set")

Path("logs").mkdir(exist_ok=True)
handler = RotatingFileHandler(
    filename="logs/logs.log",
    encoding="utf-8",
    mode="a",
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=3,
)
handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
logger = logging.getLogger("discord")
logger.setLevel(logging.INFO)
logger.addHandler(handler)


def start_healthcheck_server() -> None:
    try:
        port = int(os.getenv("PORT", "10000"))
    except ValueError:
        port = 10000

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", "/health"):
                self.send_response(404)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, _format, *_args):
            return

    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info("Healthcheck server listening on port %s", port)
    server.serve_forever()


if os.getenv("PORT"):
    Thread(target=start_healthcheck_server, daemon=True).start()

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)
bot.ai_service = None


@bot.event
async def setup_hook():
    try:
        await migrate()
        database_available = True
    except Exception as exc:
        database_available = False
        logger.warning("Database migration failed; starting with anti-phishing defaults: %s", exc)

    try:
        bot.ai_service = get_groq_client()
        logger.info("Groq /ask service initialized")
    except ValueError:
        bot.ai_service = None
        logger.warning("GROQ_API_KEY missing: /ask command is disabled")

    setup_commands(bot, groq_model=config["groq"]["model"])
    setup_channel_clear(bot)
    setup_setup(bot)
    setup_anti_phishing(
        bot,
        config["anti_phishing"],
        database_available=database_available,
        enable_database_recovery=True,
    )
    await fetch_official_blacklist(config["anti_phishing"])

    # Sync slash commands with Discord on startup.
    synced = await bot.tree.sync()
    logger.info("Synced %s slash command(s)", len(synced))


@bot.event
async def on_ready():
    print(f"{bot.user.name} has connected to Discord!")


bot.run(token, log_handler=handler, log_level=logging.DEBUG)
