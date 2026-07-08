from unittest.mock import MagicMock

import discord

from anti_phishing.actions import _action_past, _parse_duration, is_moderator


class TestParseDuration:
    def test_seven_days(self):
        assert _parse_duration("7d") == 604800

    def test_two_weeks(self):
        assert _parse_duration("2w") == 1209600

    def test_twenty_eight_days(self):
        assert _parse_duration("28d") == 2419200

    def test_clamped_to_max(self):
        assert _parse_duration("999d") == 2419200

    def test_garbage_input_returns_default(self):
        assert _parse_duration("garbage") == 604800

    def test_integer_seconds(self):
        assert _parse_duration("3600") == 3600

    def test_integer_clamped(self):
        assert _parse_duration("99999999") == 2419200

    def test_empty_string(self):
        assert _parse_duration("") == 604800


class TestActionPast:
    def test_timeout(self):
        assert _action_past("timeout") == "timed out"

    def test_kick(self):
        assert _action_past("kick") == "kicked"

    def test_ban(self):
        assert _action_past("ban") == "banned"

    def test_warn(self):
        assert _action_past("warn") == "warned"

    def test_unknown_fallback(self):
        assert _action_past("unknown") == "unknowned"


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
