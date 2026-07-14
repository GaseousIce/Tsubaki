import json
from unittest.mock import MagicMock, patch

import discord
import pytest
import simcord.asserts
from simcord.backend.errors import BackendError


async def _grant_mod_perms(env, guild):
    """Give the bot moderate_members permission so it can timeout users."""
    bot_member = env.bot.get_guild(guild.id).get_member(env.bot.user.id)
    mod_role = guild.create_role("Admin", permissions=discord.Permissions(moderate_members=True))
    role = env.bot.get_guild(guild.id).get_role(mod_role.id)
    await bot_member.add_roles(role)


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

    async def test_phishing_url_deleted(self, simcord_env, mock_db, real_official_domains):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        domain = real_official_domains[0]
        await alice.send(channel, f"Free nitro! https://{domain}/steam")

        msg = channel.last_message
        assert msg is None or domain not in (msg.content or "")

    async def test_guild_disabled(self, simcord_env, mock_db, real_official_domains):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        stored = json.dumps({"enabled": False})

        async def side_effect(sql, params=None):
            if "SELECT config FROM guild_configs" in sql:
                return MagicMock(rows=[(stored,)])
            return MagicMock(rows=[])

        mock_db.execute.side_effect = side_effect

        domain = real_official_domains[0]
        await alice.send(channel, f"https://{domain}/steam")

        msg = channel.last_message
        assert msg is not None
        assert domain in msg.content


class TestOnMessageExceptionPaths:
    async def test_extract_urls_failure_skips(self, simcord_env, mock_db, real_official_domains):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        domain = real_official_domains[0]
        with patch("anti_phishing.domain.extract_urls", side_effect=Exception("crash")):
            await alice.send(channel, f"https://{domain}/steam")

        msg = channel.last_message
        assert msg is not None
        assert domain in msg.content

    async def test_find_in_blacklists_failure_skips(self, simcord_env, mock_db, real_official_domains):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        domain = real_official_domains[0]
        with patch("anti_phishing.domain.find_in_blacklists", side_effect=Exception("crash")):
            await alice.send(channel, f"https://{domain}/steam")

        msg = channel.last_message
        assert msg is not None
        assert domain in msg.content

    async def test_handle_detection_exception_logged(self, simcord_env, mock_db, real_official_domains):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        domain = real_official_domains[0]
        with patch("anti_phishing.actions.handle_detection", side_effect=Exception("oops")):
            await alice.send(channel, f"https://{domain}/steam")

        msg = channel.last_message
        assert msg is not None
        assert domain in msg.content


class TestAntiPhishingEdgeCases:
    async def test_bypass_role_skips_detection(self, simcord_env, mock_db, real_official_domains):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        bypass_role = guild.create_role("Bypass")
        alice = guild.add_member(simcord_env.create_user("alice"), roles=[bypass_role])

        cfg = json.dumps({"bypass_role": bypass_role.id})

        async def side_effect(sql, params=None):
            if "SELECT config FROM guild_configs" in sql:
                return MagicMock(rows=[(cfg,)])
            return MagicMock(rows=[])

        mock_db.execute.side_effect = side_effect

        domain = real_official_domains[0]
        await alice.send(channel, f"https://{domain}/steam")

        msg = channel.last_message
        assert msg is not None
        assert domain in msg.content

    async def test_db_failure_skips_gracefully(self, simcord_env, mock_db, real_official_domains):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        mock_db.execute.side_effect = Exception("DB is down")

        domain = real_official_domains[0]
        await alice.send(channel, f"https://{domain}/steam")

        msg = channel.last_message
        assert msg is not None
        assert domain in msg.content


class TestPhishingPunishment:
    async def test_blacklist_punishes_and_alerts_once(self, simcord_env, mock_db, real_official_domains):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alerts = guild.create_text_channel("alerts")
        alice = guild.add_member(simcord_env.create_user("alice"))

        await _grant_mod_perms(simcord_env, guild)

        cfg = json.dumps({"alert_channels": [alerts.id]})

        async def side_effect(sql, params=None):
            if "SELECT config FROM guild_configs" in sql:
                return MagicMock(rows=[(cfg,)])
            return MagicMock(rows=[])

        mock_db.execute.side_effect = side_effect

        domain = real_official_domains[0]

        # Send a blacklisted link — gets deleted, Alice timed out, 1 alert
        await alice.send(channel, f"https://{domain}/steam")

        assert channel.last_message is None or domain not in str(channel.last_message.content or "")
        assert alice.member.timed_out_until is not None
        assert len(alerts.history()) == 1

        # Alice is timed out — every send fails
        with pytest.raises(BackendError):
            await alice.send(channel, "https://google.com/free")
        with pytest.raises(BackendError):
            await alice.send(channel, "i promise it was an accident")

        # Still exactly 1 alert
        assert len(alerts.history()) == 1

    async def test_rate_limit_punishes_and_alerts_once(self, simcord_env_rate, mock_db, official_domains):
        guild = simcord_env_rate.create_guild()
        ch1 = guild.create_text_channel("ch1")
        ch2 = guild.create_text_channel("ch2")
        ch3 = guild.create_text_channel("ch3")
        ch4 = guild.create_text_channel("ch4")
        alerts = guild.create_text_channel("alerts")
        alice = guild.add_member(simcord_env_rate.create_user("alice"))

        await _grant_mod_perms(simcord_env_rate, guild)

        cfg = json.dumps({"alert_channels": [alerts.id]})

        async def side_effect(sql, params=None):
            if "SELECT config FROM guild_configs" in sql:
                return MagicMock(rows=[(cfg,)])
            return MagicMock(rows=[])

        mock_db.execute.side_effect = side_effect

        # Send links across channels — third triggers rate limit
        # (domains NOT in official_domains so blacklist doesn't interfere)
        await alice.send(ch1, "https://suspicious.net/a")
        await alice.send(ch2, "https://suspicious.net/b")
        await alice.send(ch3, "https://suspicious.net/c")  # rate limit tripped

        assert alice.member.timed_out_until is not None
        assert len(alerts.history()) == 1

        # Alice is timed out — every send fails
        with pytest.raises(BackendError):
            await alice.send(ch4, "https://suspicious.net/d")
        with pytest.raises(BackendError):
            await alice.send(ch1, "https://google.com")

        assert len(alerts.history()) == 1

    async def test_rate_limit_no_urls_still_punishes(self, simcord_env_rate, mock_db, official_domains):
        """Same non-URL content in 2+ channels triggers rate limit via content hash."""
        guild = simcord_env_rate.create_guild()
        ch1 = guild.create_text_channel("ch1")
        ch2 = guild.create_text_channel("ch2")
        alerts = guild.create_text_channel("alerts")
        alice = guild.add_member(simcord_env_rate.create_user("alice"))

        await _grant_mod_perms(simcord_env_rate, guild)

        cfg = json.dumps({"alert_channels": [alerts.id]})

        async def side_effect(sql, params=None):
            if "SELECT config FROM guild_configs" in sql:
                return MagicMock(rows=[(cfg,)])
            return MagicMock(rows=[])

        mock_db.execute.side_effect = side_effect

        await alice.send(ch1, "same text, no urls here")
        await alice.send(ch2, "same text, no urls here")

        assert alice.member.timed_out_until is not None
        assert len(alerts.history()) == 1

    async def test_rate_limit_add_to_blocklist_retries_on_error(self, simcord_env_rate, mock_db, official_domains):
        """add_to_blocklist failing during rate limit doesn't crash the handler."""
        guild = simcord_env_rate.create_guild()
        ch1 = guild.create_text_channel("ch1")
        ch2 = guild.create_text_channel("ch2")
        ch3 = guild.create_text_channel("ch3")
        alerts = guild.create_text_channel("alerts")
        alice = guild.add_member(simcord_env_rate.create_user("alice"))

        await _grant_mod_perms(simcord_env_rate, guild)

        cfg = json.dumps({"alert_channels": [alerts.id]})

        async def side_effect(sql, params=None):
            if "SELECT config FROM guild_configs" in sql:
                return MagicMock(rows=[(cfg,)])
            return MagicMock(rows=[])

        mock_db.execute.side_effect = side_effect

        with patch("anti_phishing.db.add_to_blocklist", side_effect=Exception("DB error")):
            await alice.send(ch1, "https://suspicious.net/a")
            await alice.send(ch2, "https://suspicious.net/b")
            await alice.send(ch3, "https://suspicious.net/c")

        assert alice.member.timed_out_until is not None
        assert len(alerts.history()) == 1


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
        embed_str = str(embed_dict)
        assert "Total detections" in embed_str
        assert "5" in embed_str
        assert "evil.com" in embed_str
        assert "official_blacklist" in embed_str

    async def test_settings_command(self, simcord_env):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        result = await alice.slash(channel, "antiphishing settings")

        followup = result.followups[0] if result.followups else None
        assert followup is not None
        embed_dict = followup.embeds[0].to_dict() if followup.embeds else {}
        embed_str = str(embed_dict)
        assert "Status" in embed_str
        assert "Enabled" in embed_str

    async def test_configure_command(self, simcord_env, mock_db):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        result = await alice.slash(channel, "antiphishing configure", enabled=False, action="kick")

        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert "successfully updated" in followup.content


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
