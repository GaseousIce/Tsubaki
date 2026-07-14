from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from anti_phishing.actions import (
    PhishingAlertView,
    _build_dm_embed,
    _parse_duration,
    handle_detection,
    is_moderator,
)


class TestParseDuration:
    @pytest.mark.parametrize(
        "duration,expected",
        [
            ("7d", 604800),
            ("2w", 1209600),
            ("28d", 2419200),
            ("999d", 2419200),
            ("garbage", 604800),
            ("3600", 3600),
            ("99999999", 2419200),
            ("", 604800),
        ],
    )
    def test_parse(self, duration, expected):
        assert _parse_duration(duration) == expected


class TestBuildDmEmbed:
    @pytest.mark.parametrize(
        "guild,url,action,dm_msg,check_desc,check_action",
        [
            ("Test Guild", "https://evil.com", "timeout", None, "https://evil.com", "timed out"),
            ("Test Guild", "https://evil.com", "ban", "Custom alert!", "Custom alert!", "banned"),
            ("Test Guild", None, "warn", None, "unknown", None),
            ("Test Guild", "https://evil.com", "kick", None, "https://evil.com", "kicked"),
        ],
    )
    def test_build(self, guild, url, action, dm_msg, check_desc, check_action):
        embed = _build_dm_embed(guild, url, action, dm_msg)
        data = embed.to_dict()
        assert data["title"] == "🛡️ Account Compromised - Security Alert"
        if check_desc in data["description"]:
            pass
        elif check_desc == "Custom alert!":
            assert data["description"] == "Custom alert!"
        elif check_desc == "unknown":
            assert "unknown" in data["description"]
        else:
            assert check_desc in data["description"]
        if check_action:
            assert check_action in str(data)


class TestIsModerator:
    @staticmethod
    def make_member(is_admin=False, role_ids=None):
        member = MagicMock(spec=discord.Member)
        member.id = 12345
        member.guild_permissions = discord.Permissions(administrator=is_admin)
        member.roles = [MagicMock(spec=discord.Role, id=rid) for rid in (role_ids or [])]
        return member

    async def test_discord_user_returns_false(self):
        user = MagicMock(spec=discord.User, id=12345)
        result = await is_moderator(user, {})
        assert result is False

    async def test_administrator_returns_true(self):
        result = await is_moderator(self.make_member(is_admin=True), {})
        assert result is True

    async def test_matching_mod_role_returns_true(self):
        result = await is_moderator(self.make_member(role_ids=[999]), {"mod_roles": [999]})
        assert result is True

    async def test_no_mod_role_returns_false(self):
        result = await is_moderator(self.make_member(), {"mod_roles": [999]})
        assert result is False

    async def test_mod_roles_not_in_config(self):
        result = await is_moderator(self.make_member(), {})
        assert result is False


class TestHandleDetectionActions:
    @staticmethod
    def _make_mock_message():
        message = MagicMock(spec=discord.Message)
        message.guild = MagicMock()
        message.guild.id = 123
        message.guild.name = "Test Guild"
        message.guild.get_channel = MagicMock(return_value=None)
        message.author.id = 456
        message.channel.mention = "#general"
        message.delete = AsyncMock()
        return message

    @staticmethod
    def _make_mock_member():
        member = MagicMock(spec=discord.Member)
        member.id = 456
        member.mention = "<@456>"
        member.send = AsyncMock()
        member.timeout = AsyncMock()
        member.kick = AsyncMock()
        member.ban = AsyncMock()
        return member

    async def test_action_kick(self, mock_db):
        message = self._make_mock_message()
        member = self._make_mock_member()
        guild_cfg = {"action": "kick", "alert_channels": []}

        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        member.kick.assert_awaited_once()
        member.timeout.assert_not_called()
        member.ban.assert_not_called()
        message.delete.assert_awaited_once()
        member.send.assert_awaited_once()

    async def test_action_ban(self, mock_db):
        message = self._make_mock_message()
        member = self._make_mock_member()
        guild_cfg = {"action": "ban", "alert_channels": []}

        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        member.ban.assert_awaited_once()
        member.timeout.assert_not_called()
        member.kick.assert_not_called()

    async def test_action_warn(self, mock_db):
        message = self._make_mock_message()
        member = self._make_mock_member()
        guild_cfg = {"action": "warn", "alert_channels": []}

        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        member.timeout.assert_not_called()
        member.kick.assert_not_called()
        member.ban.assert_not_called()
        message.delete.assert_awaited_once()
        member.send.assert_awaited_once()

    async def test_timeout_default_action(self, mock_db):
        message = self._make_mock_message()
        member = self._make_mock_member()
        guild_cfg = {"alert_channels": []}

        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        member.timeout.assert_awaited_once()
        member.kick.assert_not_called()
        member.ban.assert_not_called()

    async def test_member_none_fetches(self):
        message = self._make_mock_message()
        member_fetched = self._make_mock_member()
        message.guild.fetch_member = AsyncMock(return_value=member_fetched)
        guild_cfg = {"action": "timeout", "alert_channels": []}

        await handle_detection(message, None, guild_cfg, "https://evil.com", "official_blacklist")

        message.guild.fetch_member.assert_awaited_once_with(456)
        member_fetched.timeout.assert_awaited_once()

    async def test_member_not_found_returns_early(self, mock_db):
        message = self._make_mock_message()
        message.guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(), "not found"))
        guild_cfg = {"action": "timeout", "alert_channels": []}

        await handle_detection(message, None, guild_cfg, "https://evil.com", "official_blacklist")

        message.guild.fetch_member.assert_awaited_once_with(456)
        message.delete.assert_not_called()

    async def test_db_log_detection_failure_continues(self, mock_db):
        message = self._make_mock_message()
        member = self._make_mock_member()
        guild_cfg = {"action": "timeout", "alert_channels": []}

        with patch("anti_phishing.actions.db.log_detection", side_effect=Exception("DB down")):
            await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        member.timeout.assert_awaited_once()
        message.delete.assert_awaited_once()

    async def test_message_delete_forbidden_continues(self, mock_db):
        message = self._make_mock_message()
        message.delete = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no permission"))
        member = self._make_mock_member()
        guild_cfg = {"action": "timeout", "alert_channels": []}

        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        member.timeout.assert_awaited_once()
        member.send.assert_awaited_once()

    async def test_message_delete_notfound_continues(self, mock_db):
        message = self._make_mock_message()
        message.delete = AsyncMock(side_effect=discord.NotFound(MagicMock(), "not found"))
        member = self._make_mock_member()
        guild_cfg = {"action": "timeout", "alert_channels": []}

        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        member.timeout.assert_awaited_once()
        member.send.assert_awaited_once()

    async def test_member_send_forbidden_continues(self, mock_db):
        message = self._make_mock_message()
        member = self._make_mock_member()
        member.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "DMs closed"))
        guild_cfg = {"action": "timeout", "alert_channels": []}

        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        member.timeout.assert_awaited_once()
        message.delete.assert_awaited_once()


class TestPhishingAlertViewCallbacks:
    @staticmethod
    def _make_interaction():
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.message.embeds = [discord.Embed(description="Test")]
        interaction.message.edit = AsyncMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 999
        interaction.user.guild_permissions = discord.Permissions(administrator=True)
        interaction.user.mention = "<@999>"
        interaction.user.roles = []
        return interaction

    @staticmethod
    def _make_member():
        member = MagicMock(spec=discord.Member)
        member.id = 456
        member.mention = "<@456>"
        return member

    async def test_pardon_callback_success(self):
        member = self._make_member()
        member.edit = AsyncMock()

        view = PhishingAlertView(member, "https://evil.com", "timeout", {"mod_roles": []})
        interaction = self._make_interaction()

        await view.pardon_callback(interaction)

        assert member.edit.call_count == 1
        interaction.message.edit.assert_awaited_once()
        interaction.followup.send.assert_awaited_once()

    async def test_ban_callback_success(self):
        member = self._make_member()
        member.ban = AsyncMock()

        view = PhishingAlertView(member, "https://evil.com", "timeout", {"mod_roles": []})
        interaction = self._make_interaction()

        await view.ban_callback(interaction)

        assert member.ban.call_count == 1
        interaction.message.edit.assert_awaited_once()
        interaction.followup.send.assert_awaited_once()

    async def test_allow_callback_success(self, mock_db):
        member = self._make_member()

        view = PhishingAlertView(member, "https://allowed.com", "timeout", {"mod_roles": []})
        interaction = self._make_interaction()

        await view.allow_callback(interaction)

        interaction.message.edit.assert_awaited_once()
        interaction.followup.send.assert_awaited_once()

    async def test_allow_callback_no_url(self):
        member = self._make_member()

        view = PhishingAlertView(member, None, "timeout", {"mod_roles": []})
        interaction = self._make_interaction()

        await view.allow_callback(interaction)

        interaction.message.edit.assert_not_called()
        interaction.followup.send.assert_awaited_once_with("❌ URL is not set or unknown.", ephemeral=True)

    async def test_interaction_check_non_moderator_rejected(self):
        member = self._make_member()
        view = PhishingAlertView(member, "https://evil.com", "timeout", {"mod_roles": [999]})

        interaction = self._make_interaction()
        interaction.user.roles = []
        interaction.user.guild_permissions = discord.Permissions(administrator=False)
        interaction.response.send_message = AsyncMock()

        result = await view.interaction_check(interaction)

        assert result is False
        interaction.response.send_message.assert_awaited_once()
