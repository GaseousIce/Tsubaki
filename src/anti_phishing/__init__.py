import logging

import discord
from discord.ext import commands

import db
from anti_phishing import actions, domain, rate_limit
from anti_phishing.commands import antiphishing
from anti_phishing.config import get_guild_cfg
from config import AntiPhishingConfig

logger = logging.getLogger("discord")


def setup(bot: commands.Bot, config: AntiPhishingConfig) -> None:
    """
    Register the on_message listener and /antiphishing command group.
    Call this from setup_hook() after migrate().
    """

    async def on_message(message: discord.Message) -> None:
        # Ignore DMs and bot messages.
        if not message.guild or message.author.bot:
            return

        member = message.guild.get_member(message.author.id)

        # Fetch per-guild config; skip if disabled or DB is down.
        try:
            guild_cfg = await get_guild_cfg(message.guild.id)
        except Exception as exc:
            logger.warning("DB get_guild_cfg failed in on_message: %s", exc)
            return

        if not guild_cfg.get("enabled", True):
            return

        # Bypass role check.
        bypass_role_id = guild_cfg.get("bypass_role", 0)
        if member and bypass_role_id and any(r.id == bypass_role_id for r in member.roles):
            return

        # --- Detection pipeline ---
        detected_url: str | None = None
        reason: str | None = None

        # 1. Extract URLs and check blacklists.
        try:
            extracted_urls = domain.extract_urls(message.content, message.embeds)
        except Exception:
            extracted_urls = []

        if extracted_urls:
            try:
                detected_url, reason = await domain.find_in_blacklists(extracted_urls)
            except Exception as exc:
                logger.warning("find_in_blacklists error: %s", exc)

        # 2. Rate-limit heuristic.
        if not reason:
            if config.rate_enabled and rate_limit.rate_limit_check(
                message.author.id,
                message.channel.id,
                message.content,
                config.rate_window,
                config.rate_threshold,
            ):
                reason = "rate_limit"
                if extracted_urls:
                    detected_url = extracted_urls[0]
                    for url in extracted_urls:
                        try:
                            await db.add_to_blocklist(url, "rate_limit")
                        except Exception as exc:
                            logger.warning("add_to_blocklist rate_limit failed for %s: %s", url, exc)
                else:
                    detected_url = None

        if reason:
            rate_limit.clear_user(message.author.id)
            try:
                await actions.handle_detection(message, member, guild_cfg, detected_url, reason)
            except Exception as exc:
                logger.exception("handle_detection raised unexpectedly: %s", exc)

    bot.add_listener(on_message)
    bot.tree.add_command(antiphishing)
    logger.info("Anti-phishing setup complete")


async def fetch_official_blacklist(config: AntiPhishingConfig) -> None:
    """
    Fetch the official phishing domain list into domain.official.
    Called from setup_hook() after setup().
    On complete failure, posts no embed (callers handle alerting if needed).
    """
    fetched = await domain.fetch_blacklist(config.fetch_retries)
    domain.official.update(fetched)
    if fetched:
        logger.info("Loaded %d official phishing domains", len(fetched))
    else:
        logger.warning("Official phishing blacklist could not be fetched — relying on DB blocklist + patterns")
