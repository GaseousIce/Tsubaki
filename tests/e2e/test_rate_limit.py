"""Tier 1: Feature Coverage — Rate Limit Heuristic.

Covers at least 5 test cases verifying multi-channel link spreading detection,
channel thresholds, user isolation, and alert logging under simcord_env_rate.
"""

from .helpers import (
    create_regular_member,
    grant_bot_permissions,
    set_guild_alert_channel,
)


class TestTier1RateLimitFeature:
    """Opaque-box feature coverage for multi-channel link spreading rate limiter."""

    async def test_rate_limit_multi_channel_link_spreading(self, simcord_env_rate):
        """User posting links across 3 distinct channels within window is punished for rate limit."""
        guild = simcord_env_rate.create_guild()
        ch1 = guild.create_text_channel("channel-1")
        ch2 = guild.create_text_channel("channel-2")
        ch3 = guild.create_text_channel("channel-3")
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

        # Alice posts links across 3 distinct channels
        await alice.send(ch1, "Check this link: https://innocent-site.net/page1")
        await alice.send(ch2, "Check this link: https://innocent-site.net/page2")
        await alice.send(ch3, "Check this link: https://innocent-site.net/page3")

        # Third message in 3rd channel triggers rate limit punishment
        assert alice.member.timed_out_until is not None
        assert len(alerts.history()) == 1

        alert_embed = alerts.history()[0].embeds[0]
        assert "rate_limit" in alert_embed.description

    async def test_rate_limit_single_channel_allowed(self, simcord_env_rate):
        """Posting multiple different links within a single channel does not trigger rate limit."""
        guild = simcord_env_rate.create_guild()
        channel = guild.create_text_channel("general")
        alice = create_regular_member(simcord_env_rate, guild, "alice")
        await grant_bot_permissions(simcord_env_rate, guild, moderate_members=True, manage_messages=True)

        await alice.send(channel, "Link one https://example.com/one")
        await alice.send(channel, "Link two https://example.com/two")
        await alice.send(channel, "Link three https://example.com/three")

        assert len(channel.history()) == 3
        assert alice.member.timed_out_until is None

    async def test_rate_limit_two_channels_sub_threshold(self, simcord_env_rate):
        """Posting distinct links across only 2 channels remains under the 3-channel threshold."""
        guild = simcord_env_rate.create_guild()
        ch1 = guild.create_text_channel("ch1")
        ch2 = guild.create_text_channel("ch2")
        alice = create_regular_member(simcord_env_rate, guild, "alice")
        await grant_bot_permissions(simcord_env_rate, guild, moderate_members=True, manage_messages=True)

        await alice.send(ch1, "Link A https://example.com/a")
        await alice.send(ch2, "Link B https://example.com/b")

        assert alice.member.timed_out_until is None
        assert len(ch1.history()) == 1
        assert len(ch2.history()) == 1

    async def test_rate_limit_user_isolation(self, simcord_env_rate):
        """Activity from different users does not accumulate toward rate limits."""
        guild = simcord_env_rate.create_guild()
        ch1 = guild.create_text_channel("ch1")
        ch2 = guild.create_text_channel("ch2")
        alice = create_regular_member(simcord_env_rate, guild, "alice")
        bob = create_regular_member(simcord_env_rate, guild, "bob")
        await grant_bot_permissions(simcord_env_rate, guild, moderate_members=True, manage_messages=True)

        # Alice sends in ch1 and ch2 (2 channels)
        await alice.send(ch1, "Alice link 1 https://site1.com")
        await alice.send(ch2, "Alice link 2 https://site2.com")

        # Bob sends in ch1 and ch2 (2 channels)
        await bob.send(ch1, "Bob link 1 https://site3.com")
        await bob.send(ch2, "Bob link 2 https://site4.com")

        # Neither user reached threshold of 3 channels
        assert alice.member.timed_out_until is None
        assert bob.member.timed_out_until is None

    async def test_rate_limit_identical_content_cross_channel(self, simcord_env_rate):
        """Posting exact identical content across 2 channels triggers duplicate message rate limit."""
        guild = simcord_env_rate.create_guild()
        ch1 = guild.create_text_channel("ch1")
        ch2 = guild.create_text_channel("ch2")
        alice = create_regular_member(simcord_env_rate, guild, "alice")
        await grant_bot_permissions(simcord_env_rate, guild, moderate_members=True, manage_messages=True)

        spam_text = "Join my free giveaway at https://giveaway.gg"
        await alice.send(ch1, spam_text)
        await alice.send(ch2, spam_text)

        # Cross-channel duplicate content triggers rate limit
        assert alice.member.timed_out_until is not None

    async def test_rate_limit_alert_contains_full_metadata(self, simcord_env_rate):
        """Rate limit alert embed contains user mention, detected reason, and message preview."""
        guild = simcord_env_rate.create_guild()
        ch1 = guild.create_text_channel("ch1")
        ch2 = guild.create_text_channel("ch2")
        ch3 = guild.create_text_channel("ch3")
        alerts = guild.create_text_channel("mod-alerts")
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

        await alice.send(ch1, "https://test.net/1")
        await alice.send(ch2, "https://test.net/2")
        final_msg = "https://test.net/3"
        await alice.send(ch3, final_msg)

        assert len(alerts.history()) == 1
        embed = alerts.history()[0].embeds[0]
        assert str(alice.id) in embed.description
        assert "rate_limit" in embed.description

        field_map = {f.name: f.value for f in embed.fields}
        assert "Message Content" in field_map
        assert final_msg in field_map["Message Content"]
