"""Tier 3: Cross-Feature Combinations.

Covers pairwise and multi-feature interactions across modules:
- Rate limit + Blacklist detection
- Clear + Channel-specific permission loss
- Setup + Database outage
- Anti-phishing + Database outage
- /test inspection + Anti-phishing pipeline safety
- Settings configuration + Detection action execution
- Channel clear + In-memory rate limiting persistence
"""

from unittest.mock import AsyncMock, patch

import db

from .helpers import (
    create_admin_member,
    create_mod_member,
    create_regular_member,
    grant_bot_permissions,
    set_guild_alert_channel,
)


class TestTier3CrossFeatureCombinations:
    """Opaque-box cross-feature combination test suite."""

    async def test_pairwise_rate_limit_and_blacklist_priority(self, simcord_env_rate, official_domains):
        """When user posts a blacklisted URL across channels, blacklist detection triggers first."""
        guild = simcord_env_rate.create_guild()
        ch1 = guild.create_text_channel("chat-1")
        ch2 = guild.create_text_channel("chat-2")
        alerts = guild.create_text_channel("alerts")
        alice = create_regular_member(simcord_env_rate, guild, "alice")

        await grant_bot_permissions(
            simcord_env_rate,
            guild,
            moderate_members=True,
            manage_messages=True,
            view_channel=True,
            send_messages=True,
            embed_links=True,
        )
        await set_guild_alert_channel(guild.id, alerts.id)

        target_domain = next(iter(official_domains))

        # Alice sends blacklisted domain in ch1 -> blacklist triggers immediately
        await alice.send(ch1, f"Claim nitro at https://{target_domain}/free")

        assert len(ch1.history()) == 0
        assert alice.member.timed_out_until is not None
        assert len(alerts.history()) == 1

        alert_embed = alerts.history()[0].embeds[0]
        assert "official_blacklist" in alert_embed.description
        assert len(ch2.history()) == 0

    async def test_pairwise_clear_and_bot_permission_loss(self, simcord_env):
        """Moderator runs /clear in a channel where bot cannot delete messages; returns clean feedback."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("restricted-chat")
        mod = create_mod_member(simcord_env, guild, "mod", manage_messages=True)
        alice = create_regular_member(simcord_env, guild, "alice")

        await alice.send(channel, "Untouchable message")

        # Mock purge_channel returning None as happens when bot lacks permissions
        with patch("channel_clear.purge_channel", new_callable=AsyncMock, return_value=None):
            result = await mod.slash(channel, "clear", limit=5)

        assert result.followups
        assert "❌ I don't have permission to delete messages here." in result.followups[0].content
        assert len(channel.history()) == 1

    async def test_pairwise_setup_during_database_outage(self, simcord_env):
        """Running /setup when database client is unreachable fails gracefully with descriptive error."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        admin = create_admin_member(simcord_env, guild, "admin")

        with patch("setup.db.get_or_create_guild_config", side_effect=ConnectionError("Database offline")):
            result = await admin.slash(channel, "setup")

        assert result.followups
        assert result.followups[0].embeds
        fields = {f.name: f.value for f in result.followups[0].embeds[0].fields}
        assert "💾 Database" in fields
        assert "unreachable" in fields["💾 Database"]

    async def test_pairwise_anti_phishing_during_database_outage(self, simcord_env, official_domains):
        """When database is down, anti-phishing uses default config, deletes link, and applies punishment."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        alice = create_regular_member(simcord_env, guild, "alice")
        await grant_bot_permissions(simcord_env, guild, moderate_members=True, manage_messages=True)

        target_domain = next(iter(official_domains))

        with (
            patch("anti_phishing.db.get_or_create_guild_config", side_effect=RuntimeError("Turso DB unreachable")),
            patch("anti_phishing.actions.db.log_detection") as mock_log,
        ):
            await alice.send(channel, f"Visit https://{target_domain}/login")

        # Threat was eliminated using fallback defaults
        assert len(channel.history()) == 0
        assert alice.member.timed_out_until is not None
        # Logging was gracefully bypassed without exception
        mock_log.assert_not_awaited()

    async def test_pairwise_test_command_phishing_inspection_without_action(self, simcord_env, official_domains):
        """The /test command inspects a phishing message and logs the threat without deleting or punishing."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        logs = guild.create_text_channel("mod-logs")
        mod = create_mod_member(simcord_env, guild, "moderator", manage_messages=True)
        alice = create_regular_member(simcord_env, guild, "alice")

        target_domain = next(iter(official_domains))
        phish_text = f"Suspicious message https://{target_domain}/claim"

        # Alice sends message while listener is bypassed to simulate an unmoderated historical message
        with patch("anti_phishing.actions.handle_detection", new_callable=AsyncMock):
            await alice.send(channel, phish_text)

        target_msg = channel.last_message
        assert target_msg is not None

        result = await mod.slash(channel, "test", message_id=str(target_msg.id))

        assert result.followups
        assert "No action was taken" in result.followups[0].content

        # Message is NOT deleted
        assert channel.last_message.id == target_msg.id
        # Alice is NOT timed out
        assert alice.member.timed_out_until is None

        # Logs channel received inspection embed flagging threat
        assert len(logs.history()) == 1
        embed = logs.history()[0].embeds[0]
        assert target_domain in embed.description
        assert "official_blacklist" in embed.description

    async def test_pairwise_settings_update_propagates_to_detection_action(self, simcord_env, official_domains):
        """Updating guild punishment from timeout to kick executes kick on subsequent detections."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        alice = create_regular_member(simcord_env, guild, "alice")
        await grant_bot_permissions(
            simcord_env,
            guild,
            moderate_members=True,
            manage_messages=True,
            kick_members=True,
        )

        # Reconfigure guild action to kick
        await db.update_guild_config(guild.id, action="kick")

        target_domain = next(iter(official_domains))
        await alice.send(channel, f"Get it now: https://{target_domain}/promo")

        # Message is deleted
        assert len(channel.history()) == 0
        # Alice was kicked (removed from guild members)
        assert simcord_env.bot.get_guild(guild.id).get_member(alice.id) is None

    async def test_pairwise_channel_purge_does_not_reset_rate_limits(self, simcord_env_rate):
        """Purging a channel with /clear does not clear the in-memory multi-channel link tracker."""
        guild = simcord_env_rate.create_guild()
        ch1 = guild.create_text_channel("ch1")
        ch2 = guild.create_text_channel("ch2")
        ch3 = guild.create_text_channel("ch3")
        mod = create_mod_member(simcord_env_rate, guild, "mod", manage_messages=True)
        alice = create_regular_member(simcord_env_rate, guild, "alice")
        await grant_bot_permissions(simcord_env_rate, guild, moderate_members=True, manage_messages=True)

        # Alice posts in ch1 and ch2
        await alice.send(ch1, "Link 1 https://innocent.com/1")
        await alice.send(ch2, "Link 2 https://innocent.com/2")

        # Mod purges ch1
        await mod.slash(ch1, "clear")

        # Alice posts in ch3 -> reaches 3 unique channels -> triggers rate limit
        await alice.send(ch3, "Link 3 https://innocent.com/3")

        assert alice.member.timed_out_until is not None
