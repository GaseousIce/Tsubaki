import logging

import discord
from discord.ext import commands, tasks

import db
from anti_phishing import actions, domain, rate_limit
from anti_phishing.commands import antiphishing

logger = logging.getLogger("discord")


async def backfill_guild_configs(bot: commands.Bot) -> None:
    """Persist the canonical default config for every guild the bot can see."""
    for guild in bot.guilds:
        await db.get_or_create_guild_config(guild.id)


def setup(
    bot: commands.Bot,
    config: dict,
    database_available: bool = True,
    enable_database_recovery: bool = False,
) -> None:
    """
    Register the on_message listener and /antiphishing command group.
    Call this from setup_hook() after migrate().
    """

    db_available = database_available
    backfill_complete = False
    recovery_started = False

    async def mark_database_unavailable(exc: Exception) -> None:
        nonlocal db_available
        if db_available:
            logger.warning("Database unavailable; using anti-phishing defaults: %s", exc)
        db_available = False

    async def on_message(message: discord.Message) -> None:
        nonlocal db_available
        # Ignore DMs and bot messages.
        if not message.guild or message.author.bot:
            return

        member = message.guild.get_member(message.author.id)

        # Fetch the persisted per-guild config. During an outage, use the
        # canonical defaults so in-memory protections remain active.
        try:
            guild_cfg = await db.get_or_create_guild_config(message.guild.id)
        except Exception as exc:
            await mark_database_unavailable(exc)
            guild_cfg = db.DEFAULT_GUILD_CONFIG.copy()
        else:
            db_available = True

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
        except Exception as exc:
            logger.exception("Failed to extract URLs from message: %s", exc)
            extracted_urls = []

        if extracted_urls:
            try:
                detected_url, reason = await domain.find_in_blacklists(
                    extracted_urls,
                    check_custom_blocklist=db_available,
                )
            except Exception as exc:
                logger.warning("find_in_blacklists error: %s", exc)

        # 2. Rate-limit heuristic.
        if not reason:
            if config.get("rate_enabled", True) and rate_limit.rate_limit_check(
                message.author.id,
                message.channel.id,
                message.content,
                config.get("rate_window", 10),
                config.get("rate_threshold", 3),
            ):
                reason = "rate_limit"
                if extracted_urls and db_available:
                    detected_url = extracted_urls[0]
                    for url in extracted_urls:
                        try:
                            await db.add_to_blocklist(url, "rate_limit")
                        except Exception as exc:
                            logger.warning("add_to_blocklist rate_limit failed for %s: %s", url, exc)
                else:
                    detected_url = extracted_urls[0] if extracted_urls else None

        if reason:
            rate_limit.clear_user(message.author.id)
            try:
                await actions.handle_detection(
                    message,
                    member,
                    guild_cfg,
                    detected_url,
                    reason,
                    persist=db_available,
                )
            except Exception as exc:
                logger.exception("handle_detection raised unexpectedly: %s", exc)

    async def on_guild_join(guild: discord.Guild) -> None:
        try:
            await db.get_or_create_guild_config(guild.id)
        except Exception as exc:
            await mark_database_unavailable(exc)

    @tasks.loop(hours=1.0)
    async def prune_rate_limits() -> None:
        try:
            rate_limit.prune_stale_entries()
            logger.info("Auto-pruned stale anti-phishing rate-limit entries")
        except Exception as exc:
            logger.warning("Failed to prune stale rate-limit entries: %s", exc)

    async def on_ready() -> None:
        nonlocal backfill_complete, recovery_started
        if not prune_rate_limits.is_running():
            prune_rate_limits.start()
        if enable_database_recovery and not recovery_started:
            recover_database.start()
            recovery_started = True
        if backfill_complete or not db_available:
            return
        try:
            await backfill_guild_configs(bot)
        except Exception as exc:
            await mark_database_unavailable(exc)
        else:
            backfill_complete = True

    @tasks.loop(minutes=1)
    async def recover_database() -> None:
        nonlocal db_available, backfill_complete
        if db_available:
            return
        try:
            await db.migrate()
            await backfill_guild_configs(bot)
        except Exception as exc:
            logger.warning("Database recovery attempt failed: %s", exc)
            return
        db_available = True
        backfill_complete = True
        logger.info("Database recovered; persisted anti-phishing configuration restored")

    @recover_database.before_loop
    async def before_recover_database() -> None:
        await bot.wait_until_ready()

    bot.add_listener(on_message)
    bot.add_listener(on_guild_join)
    bot.add_listener(on_ready)
    bot.tree.add_command(antiphishing)
    logger.info("Anti-phishing setup complete")


async def fetch_official_blacklist(config: dict) -> None:
    """
    Fetch the official phishing domain list into domain.official.
    Called from setup_hook() after setup().
    On complete failure, posts no embed (callers handle alerting if needed).
    """
    fetched = await domain.fetch_blacklist(config.get("fetch_retries", 3))
    domain.official.update(fetched)
    if fetched:
        logger.info("Loaded %d official phishing domains", len(fetched))
    else:
        logger.warning("Official phishing blacklist could not be fetched — relying on DB blocklist + patterns")
