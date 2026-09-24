"""Tier 1: Feature Coverage — Anti-Phishing Detection Pipeline.

Covers at least 5 test cases verifying end-to-end phishing detection,
immediate deletion, user timeout, security DM, moderator alert dispatch,
and interactive alert actions.
"""

from unittest.mock import MagicMock

import db

from .helpers import (
    create_admin_member,
    create_regular_member,
    grant_bot_permissions,
    set_guild_alert_channel,
)


class TestTier1AntiPhishingFeature:
    """Opaque-box feature coverage for anti-phishing detection pipeline."""

    async def test_phishing_url_deleted_and_timed_out(self, simcord_env, official_domains):
        """Phishing link in chat is immediately deleted and author is placed in timeout."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        alice = create_regular_member(simcord_env, guild, "alice")
        await grant_bot_permissions(simcord_env, guild, moderate_members=True, manage_messages=True)

        target_domain = next(iter(official_domains))
        await alice.send(channel, f"Check this awesome reward: https://{target_domain}/free-nitro")

        # Message is immediately deleted from channel history
        assert len(channel.history()) == 0
        assert channel.last_message is None

        # Alice is timed out
        assert alice.member.timed_out_until is not None

    async def test_phishing_alert_sent_to_configured_channel(self, simcord_env, official_domains):
        """Phishing detection dispatches an alert embed to the designated alert channel."""
        guild = simcord_env.create_guild()
        chat_ch = guild.create_text_channel("chat")
        alerts_ch = guild.create_text_channel("mod-alerts")
        alice = create_regular_member(simcord_env, guild, "alice")
        await grant_bot_permissions(
            simcord_env,
            guild,
            moderate_members=True,
            manage_messages=True,
            view_channel=True,
            send_messages=True,
            embed_links=True,
        )

        await set_guild_alert_channel(guild.id, alerts_ch.id)

        target_domain = next(iter(official_domains))
        phish_msg = f"Claim $50 gift card at https://{target_domain}/login"
        await alice.send(chat_ch, phish_msg)

        # Alerts channel received the alert
        assert len(alerts_ch.history()) == 1
        alert = alerts_ch.history()[0]
        assert len(alert.embeds) == 1

        embed = alert.embeds[0]
        assert target_domain in embed.description
        assert str(alice.id) in embed.description

        field_map = {f.name: f.value for f in embed.fields}
        assert "Message Content" in field_map
        assert phish_msg in field_map["Message Content"]

    async def test_phishing_recovery_dm_sent_to_user(self, simcord_env, official_domains):
        """Offending user receives automated security recovery instructions via direct message."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        alice = create_regular_member(simcord_env, guild, "alice")
        await grant_bot_permissions(simcord_env, guild, moderate_members=True, manage_messages=True)

        target_domain = next(iter(official_domains))
        await alice.send(channel, f"Free skins: https://{target_domain}/trade")

        # User's DM history contains security recovery guidance
        assert alice.member.dm_channel is not None
        dm_history = [m async for m in alice.member.dm_channel.history()]
        assert len(dm_history) >= 1
        dm_msg = dm_history[0]
        assert len(dm_msg.embeds) == 1
        dm_embed = dm_msg.embeds[0]
        assert "Security Alert" in dm_embed.title
        field_names = [f.name for f in dm_embed.fields]
        assert any("Reset Your Password" in name for name in field_names)
        assert any("Two-Factor Authentication" in name for name in field_names)

    async def test_legitimate_url_not_deleted(self, simcord_env, official_domains):
        """Safe non-blacklisted URLs pass through cleanly without deletion or punishment."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        alice = create_regular_member(simcord_env, guild, "alice")

        safe_msg = "Here is the official documentation: https://github.com/Tsubaki"
        await alice.send(channel, safe_msg)

        assert len(channel.history()) == 1
        assert channel.last_message.content == safe_msg
        assert alice.member.timed_out_until is None

    async def test_bypass_role_user_exempt_from_detection(self, simcord_env, official_domains):
        """Member possessing configured bypass role is completely exempt from anti-phishing actions."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        bypass_role = guild.create_role("SecurityTeam")
        alice = guild.add_member(simcord_env.create_user("alice"), roles=[bypass_role])

        await db.update_guild_config(guild.id, bypass_role=bypass_role.id)

        target_domain = next(iter(official_domains))
        msg_text = f"Sample threat: https://{target_domain}/analysis"
        await alice.send(channel, msg_text)

        assert len(channel.history()) == 1
        assert channel.last_message.content == msg_text
        assert alice.member.timed_out_until is None

    async def test_anti_phishing_disabled_allows_links(self, simcord_env, official_domains):
        """When anti-phishing is disabled in guild config, blacklisted links are not intercepted."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        alice = create_regular_member(simcord_env, guild, "alice")

        await db.update_guild_config(guild.id, enabled=False)

        target_domain = next(iter(official_domains))
        await alice.send(channel, f"https://{target_domain}/test")

        assert len(channel.history()) == 1
        assert alice.member.timed_out_until is None

    async def test_custom_blocklist_triggers_detection(self, simcord_env, mock_db):
        """Domain present in custom_blocklist database table triggers detection pipeline."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        alice = create_regular_member(simcord_env, guild, "alice")
        await grant_bot_permissions(simcord_env, guild, moderate_members=True, manage_messages=True)

        custom_domain = "custom-scam-site.org"

        # Mock database get_blocklist_source to return custom blocklist entry
        async def side_effect(sql, params=None):
            if "FROM custom_blocklist" in sql:
                row = MagicMock()
                row.__getitem__.return_value = "custom-manual"
                return MagicMock(rows=[row])
            return MagicMock(rows=[])

        mock_db.execute.side_effect = side_effect

        await alice.send(channel, f"Join now https://{custom_domain}/airdrop")

        assert len(channel.history()) == 0
        assert alice.member.timed_out_until is not None

    async def test_phishing_alert_moderator_pardon_flow(self, simcord_env, official_domains):
        """Moderator can click 'Pardon User' on the alert message to lift timeout."""
        guild = simcord_env.create_guild()
        chat_ch = guild.create_text_channel("chat")
        alerts_ch = guild.create_text_channel("alerts")
        alice = create_regular_member(simcord_env, guild, "alice")
        mod_admin = create_admin_member(simcord_env, guild, "moderator_admin")

        await grant_bot_permissions(
            simcord_env,
            guild,
            moderate_members=True,
            manage_messages=True,
            view_channel=True,
            send_messages=True,
            embed_links=True,
        )
        await set_guild_alert_channel(guild.id, alerts_ch.id)

        target_domain = next(iter(official_domains))
        await alice.send(chat_ch, f"Oops: https://{target_domain}/fake")

        # Alice is timed out
        assert alice.member.timed_out_until is not None
        assert len(alerts_ch.history()) == 1
        alert_msg = alerts_ch.history()[0]

        # Moderator clicks Pardon User button
        await mod_admin.click(alert_msg, label="Pardon User")

        # Timeout is lifted
        assert alice.member.timed_out_until is None
