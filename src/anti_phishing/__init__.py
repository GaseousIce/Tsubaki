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
        if member is None:
            return

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
        if bypass_role_id and any(r.id == bypass_role_id for r in member.roles):
            return

        # --- Detection pipeline ---
        detected_domain: str | None = None
        reason: str | None = None

        # 1. Official + custom blacklist.
        try:
            extracted = domain.extract_domains(message.content, message.embeds)
        except Exception:
            extracted = []

        if extracted:
            try:
                detected_domain, reason = await domain.find_in_blacklists(extracted)
            except Exception as exc:
                logger.warning("find_in_blacklists error: %s", exc)

        # 2. Typosquat pattern scan (only if no hit yet).
        if not reason and extracted:
            try:
                matched_domain, matched_pattern = await domain.match_typosquat(extracted)
                if matched_domain:
                    try:
                        await db.add_to_blocklist(matched_domain, "typosquat")
                    except Exception as exc:
                        logger.warning("add_to_blocklist failed: %s", exc)
                    detected_domain = matched_domain
                    reason = "pattern"
            except Exception as exc:
                logger.warning("match_typosquat error: %s", exc)

        # 3. Rate-limit heuristic.
        if not reason:
            if config.rate_enabled and rate_limit.rate_limit_check(
                message.author.id,
                message.channel.id,
                message.content,
                config.rate_window,
                config.rate_threshold,
            ):
                reason = "rate_limit"

        if reason:
            rate_limit.clear_user(message.author.id)
            try:
                await actions.handle_detection(message, member, guild_cfg, detected_domain, reason)
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
