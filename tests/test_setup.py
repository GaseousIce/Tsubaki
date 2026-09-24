from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import simcord

from setup import (
    _check_action_readiness,
    _check_alert_channels,
    _check_db_health,
    _check_guild_permissions,
    _check_role_position,
    _format_duration,
)


class TestFormatDuration:
    def test_zero(self):
        assert _format_duration(0) == "0s"

    def test_negative(self):
        assert _format_duration(-10) == "0s"

    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (86400, "1d"),
            (604800, "7d"),
            (90000, "1d 1h"),
            (86460, "1d 1m"),
            (86401, "1d 1s"),
            (3661, "1h 1m 1s"),
            (3600, "1h"),
            (45, "45s"),
        ],
    )
    def test_various(self, seconds, expected):
        assert _format_duration(seconds) == expected


class TestCheckDbHealth:
    async def test_healthy(self, mock_db):
        assert await _check_db_health() is True

    async def test_unreachable(self):
        with patch("setup.db.get_db", side_effect=Exception("down")):
            assert await _check_db_health() is False


class TestCheckRolePosition:
    @staticmethod
    def _make_guild(role_count: int, bot_position: int, bot_is_none: bool = False):
        guild = MagicMock(spec=discord.Guild)
        if bot_is_none:
            guild.me = None
            return guild
        me = MagicMock(spec=discord.Member)
        me.top_role = MagicMock(spec=discord.Role)
        me.top_role.position = bot_position
        guild.me = me
        guild.roles = [MagicMock(spec=discord.Role) for _ in range(role_count)]
        return guild

    def test_position_near_top(self):
        guild = self._make_guild(20, 17)  # rank = 20 - 17 = 3 -> ✅ (<= 3)
        msg, ok = _check_role_position(guild)
        assert ok is True
        assert "✅" in msg

    def test_position_mid(self):
        guild = self._make_guild(20, 15)  # rank = 20 - 15 = 5 -> ⚠️ (> 3)
        msg, ok = _check_role_position(guild)
        assert ok is False
        assert "⚠️" in msg

    def test_position_boundary_four(self):
        guild = self._make_guild(20, 16)  # rank = 20 - 16 = 4 -> ⚠️ (> 3)
        msg, ok = _check_role_position(guild)
        assert ok is False
        assert "⚠️" in msg

    def test_position_top(self):
        guild = self._make_guild(20, 19)  # rank = 1 -> ✅
        msg, ok = _check_role_position(guild)
        assert ok is True
        assert "✅" in msg

    def test_no_me(self):
        guild = self._make_guild(20, 0, bot_is_none=True)
        msg, ok = _check_role_position(guild)
        assert ok is False
        assert "Could not determine" in msg


class TestCheckGuildPermissions:
    @staticmethod
    def _make_me(**perms):
        me = MagicMock(spec=discord.Member)
        me.guild_permissions = discord.Permissions(**perms)
        return me

    def test_all_present(self):
        me = self._make_me(
            moderate_members=True,
            kick_members=True,
            ban_members=True,
            manage_messages=True,
            manage_roles=True,
        )
        results = _check_guild_permissions(me)
        assert all(ok for _, ok in results)
        assert len(results) == 5

    def test_all_missing(self):
        me = self._make_me()
        results = _check_guild_permissions(me)
        assert not any(ok for _, ok in results)

    def test_partial(self):
        me = self._make_me(moderate_members=True, manage_messages=True)
        results = _check_guild_permissions(me)
        result_map = dict(results)
        assert result_map["Moderate Members"] is True
        assert result_map["Kick Members"] is False
        assert result_map["Ban Members"] is False
        assert result_map["Manage Messages"] is True
        assert result_map["Manage Roles"] is False


class TestCheckActionReadiness:
    @staticmethod
    def _make_me(**perms):
        me = MagicMock(spec=discord.Member)
        me.guild_permissions = discord.Permissions(**perms)
        return me

    def test_action_timeout_has_perm(self):
        me = self._make_me(moderate_members=True)
        msg, ok = _check_action_readiness(me, "timeout")
        assert ok is True

    def test_action_timeout_missing_perm(self):
        me = self._make_me()
        msg, ok = _check_action_readiness(me, "timeout")
        assert ok is False
        assert "Moderate Members" in msg

    def test_action_kick_has_perm(self):
        me = self._make_me(kick_members=True)
        msg, ok = _check_action_readiness(me, "kick")
        assert ok is True

    def test_action_ban_missing_perm(self):
        me = self._make_me()
        msg, ok = _check_action_readiness(me, "ban")
        assert ok is False
        assert "Ban Members" in msg

    def test_action_warn_no_perm_needed(self):
        me = self._make_me()
        msg, ok = _check_action_readiness(me, "warn")
        assert ok is True


class TestCheckAlertChannels:
    @staticmethod
    def _make_guild_with_channels(channel_setup: list[tuple[int, bool, bool, bool]]):
        guild = MagicMock(spec=discord.Guild)
        me = MagicMock(spec=discord.Member)
        channels: dict[int, MagicMock] = {}
        for cid, view, send, embed in channel_setup:
            ch = MagicMock(spec=discord.TextChannel)
            ch.id = cid
            ch.mention = f"<#{cid}>"
            perms = MagicMock()
            perms.view_channel = view
            perms.send_messages = send
            perms.embed_links = embed
            ch.permissions_for.return_value = perms
            channels[cid] = ch
        guild.me = me
        guild.get_channel = lambda cid, chs=channels: chs.get(cid)
        return guild

    def test_all_ok(self):
        guild = self._make_guild_with_channels([(1, True, True, True)])
        results = _check_alert_channels(guild, [1])
        assert results[0][1] is True

    def test_missing_perms(self):
        guild = self._make_guild_with_channels([(1, True, False, True)])
        results = _check_alert_channels(guild, [1])
        assert results[0][1] is False
        assert "Send Messages" in results[0][0]

    def test_missing_view_and_embed_perms(self):
        guild = self._make_guild_with_channels([(1, False, True, False)])
        results = _check_alert_channels(guild, [1])
        assert results[0][1] is False
        assert "View Channel" in results[0][0]
        assert "Embed Links" in results[0][0]

    def test_channel_deleted(self):
        guild = self._make_guild_with_channels([])
        results = _check_alert_channels(guild, [999])
        assert results[0][1] is False
        assert "❓" in results[0][0]

    def test_no_me(self):
        guild = MagicMock(spec=discord.Guild)
        guild.me = None
        results = _check_alert_channels(guild, [1])
        assert results == []


class TestSetupCommand:
    async def test_setup_responds_with_embed(self, simcord_env):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
        admin = guild.add_member(simcord_env.create_user("admin"), roles=[admin_role])

        result = await admin.slash(channel, "setup")
        followup = result.followups[0] if result.followups else None
        assert followup is not None
        embed_dict = followup.embeds[0].to_dict() if followup.embeds else {}
        embed_str = str(embed_dict)
        assert "Tsubaki" in embed_str or "Setup" in embed_str or "Bot Role" in embed_str

    async def test_setup_missing_permissions_rejected(self, simcord_env):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        result = await alice.slash(channel, "setup")
        assert result.response is not None
        assert "do not have permission" in result.response.content
        simcord.asserts.assert_error(simcord_env, discord.app_commands.errors.MissingPermissions)

    async def test_setup_db_unreachable_renders_embed(self, simcord_env):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
        admin = guild.add_member(simcord_env.create_user("admin"), roles=[admin_role])

        with patch("setup.db.get_or_create_guild_config", side_effect=Exception("DB exploded")):
            result = await admin.slash(channel, "setup")

        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert len(followup.embeds) == 1
        embed_dict = followup.embeds[0].to_dict()
        fields = {f["name"]: f["value"] for f in embed_dict.get("fields", [])}
        assert "💾 Database" in fields
        assert "❌" in fields["💾 Database"]
        assert "unreachable" in fields["💾 Database"]

    async def test_setup_unexpected_failure_replies_error(self, simcord_env):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
        admin = guild.add_member(simcord_env.create_user("admin"), roles=[admin_role])

        with patch("setup._build_setup_embed", side_effect=RuntimeError("Embed render crashed")):
            result = await admin.slash(channel, "setup")

        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert "Setup check failed" in followup.content

    async def test_setup_cmd_error_missing_permissions_not_done(self):
        import setup as setup_mod

        bot = MagicMock()
        registered = {}

        def mock_command(**kwargs):
            def decorator(func):
                cmd = MagicMock()
                cmd.callback = func
                cmd.error = lambda f: setattr(cmd, "on_error", f) or f
                registered[kwargs.get("name", func.__name__)] = cmd
                return cmd

            return decorator

        bot.tree.command = mock_command
        setup_mod.setup(bot)
        cmd = registered["setup"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        error = discord.app_commands.MissingPermissions(["administrator"])

        await cmd.on_error(interaction, error)
        interaction.response.send_message.assert_awaited_once_with(
            "❌ You do not have permission to run this command.", ephemeral=True
        )

    async def test_setup_cmd_error_missing_permissions_done(self):
        import setup as setup_mod

        bot = MagicMock()
        registered = {}

        def mock_command(**kwargs):
            def decorator(func):
                cmd = MagicMock()
                cmd.callback = func
                cmd.error = lambda f: setattr(cmd, "on_error", f) or f
                registered[kwargs.get("name", func.__name__)] = cmd
                return cmd

            return decorator

        bot.tree.command = mock_command
        setup_mod.setup(bot)
        cmd = registered["setup"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.is_done.return_value = True
        interaction.followup.send = AsyncMock()
        error = discord.app_commands.MissingPermissions(["administrator"])

        await cmd.on_error(interaction, error)
        interaction.followup.send.assert_awaited_once_with(
            "❌ You do not have permission to run this command.", ephemeral=True
        )
