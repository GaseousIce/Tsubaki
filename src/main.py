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
from db import close_db, migrate
from groq_service import get_groq_client
from setup import setup as setup_setup

load_dotenv()
token = os.getenv("DISCORD_TOKEN")
config = load_config()

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


class HealthHandler(BaseHTTPRequestHandler):
    bot: commands.Bot | None = None

    def do_GET(self) -> None:
        if self.path not in ("/", "/health"):
            self.send_response(404)
            self.end_headers()
            return

        current_bot = self.bot or globals().get("bot")
        is_ready = current_bot is not None and current_bot.is_ready() and not current_bot.is_closed()

        if not is_ready:
            self.send_response(503)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"bot not ready")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, _format, *_args) -> None:
        return


_healthcheck_server: HTTPServer | None = None


def start_healthcheck_server(
    port: int | None = None,
    bot_instance: commands.Bot | None = None,
    host: str = "0.0.0.0",
) -> HTTPServer | None:
    global _healthcheck_server
    if port is None:
        try:
            port = int(os.getenv("PORT", "10000"))
        except ValueError:
            port = 10000

    if bot_instance is not None:
        HealthHandler.bot = bot_instance

    try:
        server = HTTPServer((host, port), HealthHandler)
        _healthcheck_server = server
    except OSError as exc:
        logger.error("Failed to bind healthcheck server to %s:%s: %s", host, port, exc)
        return None
    except Exception as exc:
        logger.error("Unexpected error starting healthcheck server on %s:%s: %s", host, port, exc)
        return None

    logger.info("Healthcheck server listening on %s:%s", host, port)
    try:
        server.serve_forever()
    except Exception as exc:
        logger.error("Healthcheck server error: %s", exc)
    finally:
        server.server_close()
    return server


intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)
bot.ai_service = None
_guild_commands_cleared = False


@bot.event
async def setup_hook() -> None:
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
    try:
        synced = await bot.tree.sync()
        logger.info("Synced %s slash command(s)", len(synced))
    except discord.HTTPException as exc:
        logger.error("Failed to sync slash commands with Discord: %s", exc)


@bot.event
async def on_ready() -> None:
    global _guild_commands_cleared
    user_name = bot.user.name if bot.user else "Tsubaki"
    print(f"{user_name} has connected to Discord!")
    if _guild_commands_cleared:
        logger.debug("Guild-specific commands already cleared; skipping on reconnect")
        return

    _guild_commands_cleared = True
    # Clear any guild-specific commands to prevent duplicates with global commands
    for guild in bot.guilds:
        try:
            bot.tree.clear_commands(guild=guild)
            await bot.tree.sync(guild=guild)
            logger.info("Cleared guild-specific commands for %s (%s) to prevent duplicates", guild.name, guild.id)
        except Exception as exc:
            logger.debug("Failed to clear guild commands for %s: %s", guild.id, exc)


_original_close = bot.close


async def custom_close() -> None:
    global _guild_commands_cleared, _healthcheck_server
    logger.info("Shutting down bot services...")

    if getattr(bot, "ai_service", None) is not None:
        ai_service = bot.ai_service
        bot.ai_service = None
        try:
            if hasattr(ai_service, "close"):
                await ai_service.close()
                logger.info("AI service closed successfully")
        except Exception as exc:
            logger.warning("Error closing AI service: %s", exc)

    try:
        await close_db()
        logger.info("Database client closed successfully")
    except Exception as exc:
        logger.warning("Error closing database: %s", exc)

    if _healthcheck_server is not None:
        try:
            _healthcheck_server.shutdown()
            _healthcheck_server.server_close()
            logger.info("Healthcheck server shut down successfully")
        except Exception as exc:
            logger.warning("Error shutting down healthcheck server: %s", exc)
        finally:
            _healthcheck_server = None

    _guild_commands_cleared = False
    await _original_close()


bot.close = custom_close


def run() -> None:
    global token
    token = token or os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN is not set")

    if os.getenv("PORT"):
        Thread(target=start_healthcheck_server, daemon=True).start()

    bot.run(token, log_handler=handler, log_level=logging.DEBUG)


if __name__ == "__main__":
    run()
