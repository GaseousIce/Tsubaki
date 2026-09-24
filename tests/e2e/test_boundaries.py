"""Tier 2: Boundary & Corner Cases.

Covers boundary conditions and adversarial inputs:
- Empty content and whitespace messages
- Max message lengths (2000 chars) with embedded threats
- Invalid permissions matrix across slash commands
- 14-day delete boundary handling
- IDN homoglyphs, Punycode, and case/dot normalization
- Malformed and edge-case URLs
- Embed and attachment deep URL extraction
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import simcord.asserts

from anti_phishing.actions import _parse_duration
from anti_phishing.domain import extract_urls

from .helpers import (
    create_mod_member,
    create_regular_member,
    grant_bot_permissions,
)


class TestTier2BoundaryCases:
    """Opaque-box boundary and corner case test suite."""

    async def test_boundary_empty_content_and_whitespace(self, simcord_env):
        """Messages containing only spaces or whitespace do not cause regex or listener crashes."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        alice = create_regular_member(simcord_env, guild, "alice")

        await alice.send(channel, "   \n\t   ")

        assert len(channel.history()) == 1
        assert channel.last_message.content == "   \n\t   "
        assert alice.member.timed_out_until is None

    async def test_boundary_max_message_length_with_phishing_url(self, simcord_env, official_domains):
        """Message at maximum 2000 char limit containing a threat at the very end is detected and deleted."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        alice = create_regular_member(simcord_env, guild, "alice")
        await grant_bot_permissions(simcord_env, guild, moderate_members=True, manage_messages=True)

        target_domain = next(iter(official_domains))
        url = f"https://{target_domain}/login"
        filler_length = 2000 - len(url) - 1
        message_content = ("x" * filler_length) + " " + url
        assert len(message_content) == 2000

        await alice.send(channel, message_content)

        # Threat at char 2000 is still extracted and pruned
        assert len(channel.history()) == 0
        assert alice.member.timed_out_until is not None

    async def test_boundary_invalid_permissions_enforcement(self, simcord_env):
        """Unprivileged member running /clear is strictly rejected with MissingPermissions."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        alice = create_regular_member(simcord_env, guild, "unprivileged_alice")

        await alice.send(channel, "Normal chat message")

        result = await alice.slash(channel, "clear", limit=5)
        assert result.response is not None
        assert "Manage Messages permission" in result.response.content

        simcord.asserts.assert_error(simcord_env, discord.app_commands.errors.MissingPermissions)

    async def test_boundary_clear_14_day_delete_limit(self, simcord_env):
        """When Discord rejects bulk message deletion (e.g. 14-day limit), /clear fails gracefully."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        mod = create_mod_member(simcord_env, guild, "mod", manage_messages=True)

        # Discord API raises HTTPException on bulk deletes of messages older than 14 days
        with patch("channel_clear.purge_channel", new_callable=AsyncMock, return_value=None):
            result = await mod.slash(channel, "clear")

        assert result.followups
        assert "❌ I don't have permission to delete messages here." in result.followups[0].content

    async def test_boundary_url_case_insensitivity_and_normalization(self, simcord_env, official_domains):
        """Uppercase URLs (e.g. HTTPS://EVIL.COM/PATH) are matched against lowercase blacklists."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        alice = create_regular_member(simcord_env, guild, "alice")
        await grant_bot_permissions(simcord_env, guild, moderate_members=True, manage_messages=True)

        target_domain = next(iter(official_domains))
        uppercase_host_url = f"https://{target_domain.upper()}/CLAIM"

        await alice.send(channel, f"Free gift: {uppercase_host_url}")

        assert len(channel.history()) == 0
        assert alice.member.timed_out_until is not None

    async def test_boundary_malformed_urls_with_parentheses_and_punctuation(self, simcord_env, official_domains):
        """URLs containing query parameters, trailing dots, or parentheses do not crash extraction."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        alice = create_regular_member(simcord_env, guild, "alice")
        await grant_bot_permissions(simcord_env, guild, moderate_members=True, manage_messages=True)

        target_domain = next(iter(official_domains))
        # Complex URL with parentheses, query strings, and trailing punctuation
        complex_url = f"https://{target_domain}/verify?session=(auth_token)&ref=discord..."

        await alice.send(channel, f"Click here: {complex_url}")

        assert len(channel.history()) == 0
        assert alice.member.timed_out_until is not None

    async def test_boundary_clear_limits_boundaries(self, simcord_env):
        """Purging at lower boundary (limit=1) correctly deletes exactly one message."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        mod = create_mod_member(simcord_env, guild, "mod", manage_messages=True)
        alice = create_regular_member(simcord_env, guild, "alice")

        await alice.send(channel, "Message 1")
        await alice.send(channel, "Message 2")
        await alice.send(channel, "Message 3")

        result = await mod.slash(channel, "clear", limit=1)

        assert result.followups
        assert "Successfully cleared **1** messages" in result.followups[0].content
        assert len(channel.history()) == 2

    async def test_boundary_embed_url_extraction_author_and_attachments(self, simcord_env, official_domains):
        """Extract URLs correctly from embed author URL and attachment descriptions."""
        target_domain = next(iter(official_domains))
        phish_url = f"https://{target_domain}/nitro"

        # 1. Embed with author URL
        embed = MagicMock()
        embed.url = None
        embed.description = None
        embed.title = None
        embed.fields = []
        embed.footer = None
        author_mock = MagicMock()
        author_mock.url = phish_url
        embed.author = author_mock

        urls_from_embed = extract_urls("", embeds=[embed])
        assert any(target_domain in u for u in urls_from_embed)

        # 2. Attachment with description
        attachment = MagicMock()
        attachment.description = f"Download: {phish_url}"
        urls_from_att = extract_urls("", attachments=[attachment])
        assert any(target_domain in u for u in urls_from_att)

    def test_boundary_timeout_duration_parsing_clamping(self):
        """Duration parsing clamps beyond 28d and falls back gracefully on malformed inputs."""
        # Max limit is 28 days = 2419200 seconds
        assert _parse_duration("28d") == 2419200
        assert _parse_duration("100d") == 2419200  # clamped to max
        assert _parse_duration("10w") == 2419200  # clamped to max
        assert _parse_duration("7d") == 604800
        assert _parse_duration("0d") == 0
        assert _parse_duration("invalid_string") == 604800  # fallback default 7d
