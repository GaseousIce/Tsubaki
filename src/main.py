import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Thread

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from anti_phishing import fetch_official_blacklist
from anti_phishing import setup as setup_anti_phishing
from channel_clear import setup as setup_channel_clear
from config import AppConfig
from db import migrate
from groq_service import GroqAskService

load_dotenv()
token = os.getenv("DISCORD_TOKEN")
app_config = AppConfig.load()

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

    class SecureHealthcheckServer(ThreadingHTTPServer):
        def finish_request(self, request, client_address):
            request.settimeout(5.0)  # 5-second timeout on requests
            super().finish_request(request, client_address)

    server = SecureHealthcheckServer(("0.0.0.0", port), HealthHandler)
    logger.info("Healthcheck server listening on port %s", port)
    server.serve_forever()


if os.getenv("PORT"):
    Thread(target=start_healthcheck_server, daemon=True).start()

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)
ai_service = None


@bot.event
async def setup_hook():
    global ai_service
    await migrate()  # DB tables must exist before any feature uses them.

    try:
        ai_service = GroqAskService(model=app_config.groq.model)
        logger.info("Groq /ask service initialized")
    except ValueError:
        ai_service = None
        logger.warning("GROQ_API_KEY missing: /ask command is disabled")

    setup_channel_clear(bot)
    setup_anti_phishing(bot, app_config.anti_phishing)
    await fetch_official_blacklist(app_config.anti_phishing)

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


@bot.tree.command(name="ask", description="Ask Tsubaki anything")
@app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
async def ask(interaction: discord.Interaction, question: str):
    if ai_service is None:
        await interaction.response.send_message("The Groq API key is not configured yet.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    try:
        answer = await ai_service.ask(question)
    except Exception:
        logger.exception("Groq request for /ask failed")
        await interaction.followup.send(
            "I ran into a Groq API error while generating a reply. Please try again shortly."
        )
        return

    if len(answer) > 2000:
        answer = f"{answer[:1997]}..."

    await interaction.followup.send(answer)


@ask.error
async def ask_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        try:
            await interaction.response.send_message(
                f"Please wait {error.retry_after:.1f} seconds before asking again.",
                ephemeral=True,
            )
        except discord.HTTPException:
            pass
    else:
        logger.error("Unhandled error in /ask command: %s", error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("An error occurred.", ephemeral=True)
            else:
                try:
                    await interaction.response.send_message("An error occurred.", ephemeral=True)
                except (discord.InteractionResponded, discord.HTTPException):
                    await interaction.followup.send("An error occurred.", ephemeral=True)
        except discord.HTTPException:
            pass


bot.run(token, log_handler=handler, log_level=logging.DEBUG)
