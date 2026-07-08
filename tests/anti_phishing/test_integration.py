import json
from unittest.mock import MagicMock

import discord
import simcord.asserts


class TestHello:
    async def test_hello_command(self, simcord_env):
        channel = simcord_env.create_guild().create_text_channel("general")
        alice = simcord_env.guild.add_member(simcord_env.create_user("alice"))

        result = await alice.slash(channel, "hello")
        assert result.response.content == "hello there! :3"

    async def test_ping_command(self, simcord_env):
        channel = simcord_env.create_guild().create_text_channel("general")
        alice = simcord_env.guild.add_member(simcord_env.create_user("alice"))

        result = await alice.slash(channel, "ping")
        assert "ms" in result.response.content


class TestAntiPhishingListener:
    async def test_safe_message_no_action(self, simcord_env):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        await alice.send(channel, "Hello everyone! How's it going?")

        msg = channel.last_message
        assert msg is not None
        assert msg.content == "Hello everyone! How's it going?"

    async def test_phishing_url_deleted(self, simcord_env, mock_db, official_domains):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        await alice.send(channel, "Free nitro! https://phishing.xyz")

        msg = channel.last_message
        assert msg is None or msg.content != "Free nitro! https://phishing.xyz"

    async def test_guild_disabled(self, simcord_env, mock_db):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        stored = json.dumps({"enabled": False})

        async def side_effect(sql, params=None):
            if "SELECT config FROM guild_configs" in sql:
                return MagicMock(rows=[(stored,)])
            return MagicMock(rows=[])

        mock_db.execute.side_effect = side_effect

        await alice.send(channel, "https://phishing.xyz")

        msg = channel.last_message
        assert msg is not None
        assert "phishing.xyz" in msg.content


class TestAntiPhishingCommands:
    async def test_stats_command(self, simcord_env, mock_db):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        async def side_effect(sql, params=None):
            if sql == "SELECT COUNT(*) as cnt FROM detection_log WHERE guild_id = ?":
                return MagicMock(rows=[(5,)])
            if sql.startswith("SELECT domain, COUNT(*)") and "GROUP BY domain" in sql:
                return MagicMock(rows=[("evil.com", 3)])
            if sql.startswith("SELECT domain, reason, timestamp") and "ORDER BY timestamp" in sql:
                return MagicMock(rows=[("evil.com", "official_blacklist", "2024-01-01")])
            return MagicMock(rows=[])

        mock_db.execute.side_effect = side_effect

        result = await alice.slash(channel, "antiphishing stats")

        followup = result.followups[0] if result.followups else None
        assert followup is not None
        embed_dict = followup.embeds[0].to_dict() if followup.embeds else {}
        assert "Total detections" in str(embed_dict)

    async def test_settings_command(self, simcord_env):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        result = await alice.slash(channel, "antiphishing settings")

        followup = result.followups[0] if result.followups else None
        assert followup is not None
        embed_dict = followup.embeds[0].to_dict() if followup.embeds else {}
        assert "Status" in str(embed_dict)


class TestChannelClear:
    async def test_clear_requires_manage_messages(self, simcord_env):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        await alice.send(channel, "message one")
        await alice.send(channel, "message two")

        result = await alice.slash(channel, "clear")
        assert result is None or result.response is None
        simcord.asserts.assert_error(simcord_env, discord.app_commands.errors.MissingPermissions)

    async def test_clear_with_permission(self, simcord_env):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        mod_role = guild.create_role("Mods", permissions=discord.Permissions(manage_messages=True))
        mod = guild.add_member(simcord_env.create_user("mod"), roles=[mod_role])

        await mod.send(channel, "message one")
        await mod.send(channel, "message two")
        await mod.send(channel, "message three")

        result = await mod.slash(channel, "clear", limit=10)

        content = result.followups[0].content if result.followups else ""
        assert "Successfully cleared" in content
