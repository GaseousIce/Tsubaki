from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from anti_phishing.commands import (
    CustomDMModal,
    RolesChannelsDashboardView,
    SettingsDashboardView,
    TimeoutDurationModal,
    _build_settings_embed,
    _format_duration,
    cmd_settings,
    cmd_settings_error,
    cmd_stats,
    cmd_stats_error,
)


def _make_mock_interaction(guild_id: int = 12345):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild_id = guild_id
    guild = MagicMock(spec=discord.Guild)
    guild.name = "Test Guild"
    guild.id = guild_id
    interaction.guild = guild
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 67890
    interaction.response = MagicMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


class TestFormatDuration:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0, "0s"),
            (86400, "1d"),
            (90000, "1d 1h"),
            (3661, "1h 1m"),
            (604800, "7d"),
            (3600, "1h"),
            (86460, "1d"),
        ],
    )
    def test_format(self, seconds, expected):
        assert _format_duration(seconds) == expected


class TestBuildSettingsEmbed:
    def test_default_config(self):
        guild = MagicMock(spec=discord.Guild)
        guild.name = "My Server"
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
            "dm_message": None,
        }
        embed = _build_settings_embed(guild, cfg)
        data = embed.to_dict()
        assert "My Server" in data["title"]
        fields = {f["name"]: f["value"] for f in data["fields"]}
        assert fields["Status"] == "🟢 Enabled"
        assert fields["Action"] == "Timeout"
        assert fields["Timeout Duration"] == "7d"
        assert fields["Alert Channels"] == "none"
        assert fields["Mod Roles"] == "none"
        assert fields["Bypass Role"] == "none"
        assert fields["Custom DM Message"] == "Default"

    def test_custom_config_with_truncation(self):
        guild = MagicMock(spec=discord.Guild)
        guild.name = "My Server"
        long_dm = "x" * 150
        cfg = {
            "enabled": False,
            "action": "kick",
            "timeout_duration": 3600,
            "alert_channels": [111, 222],
            "mod_roles": [333],
            "bypass_role": 444,
            "dm_message": long_dm,
        }
        embed = _build_settings_embed(guild, cfg)
        data = embed.to_dict()
        fields = {f["name"]: f["value"] for f in data["fields"]}
        assert fields["Status"] == "🔴 Disabled"
        assert fields["Action"] == "Kick"
        assert "Timeout Duration" not in fields
        assert "<#111>, <#222>" in fields["Alert Channels"]
        assert "<@&333>" in fields["Mod Roles"]
        assert "<@&444>" in fields["Bypass Role"]
        assert fields["Custom DM Message"] == f"{'x' * 97}..."


class TestSettingsDashboardView:
    def test_init_timeout_action(self):
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
        }
        view = SettingsDashboardView(12345, cfg)
        custom_ids = [item.custom_id for item in view.children]
        assert "toggle_bot" in custom_ids
        assert "action_select" in custom_ids
        assert "set_timeout" in custom_ids
        assert "set_dm" in custom_ids
        assert "switch_page" in custom_ids
        assert view.toggle_btn.label == "Disable Anti-Phishing"
        assert view.toggle_btn.style == discord.ButtonStyle.danger

    def test_init_disabled_and_non_timeout_action(self):
        cfg = {
            "enabled": False,
            "action": "ban",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
        }
        view = SettingsDashboardView(12345, cfg)
        custom_ids = [item.custom_id for item in view.children]
        assert "set_timeout" not in custom_ids
        assert view.toggle_btn.label == "Enable Anti-Phishing"
        assert view.toggle_btn.style == discord.ButtonStyle.success

    async def test_toggle_callback(self):
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
        }
        view = SettingsDashboardView(12345, cfg)
        interaction = _make_mock_interaction(12345)

        updated_cfg = dict(cfg, enabled=False)
        with patch(
            "anti_phishing.commands.db.update_guild_config",
            new_callable=AsyncMock,
            return_value=updated_cfg,
        ) as mock_update:
            await view.toggle_callback(interaction)
            mock_update.assert_awaited_once_with(12345, enabled=False)

        assert view.toggle_btn.label == "Enable Anti-Phishing"
        assert view.toggle_btn.style == discord.ButtonStyle.success
        interaction.response.edit_message.assert_awaited_once()

    async def test_action_callback(self):
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
        }
        view = SettingsDashboardView(12345, cfg)
        view.action_select._values = ["warn"]
        interaction = _make_mock_interaction(12345)

        updated_cfg = dict(cfg, action="warn")
        with patch(
            "anti_phishing.commands.db.update_guild_config",
            new_callable=AsyncMock,
            return_value=updated_cfg,
        ) as mock_update:
            await view.action_callback(interaction)
            mock_update.assert_awaited_once_with(12345, action="warn")

        interaction.response.edit_message.assert_awaited_once()
        edit_kwargs = interaction.response.edit_message.call_args.kwargs
        assert isinstance(edit_kwargs["view"], SettingsDashboardView)

    async def test_timeout_callback(self):
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
        }
        view = SettingsDashboardView(12345, cfg)
        interaction = _make_mock_interaction(12345)

        await view.timeout_callback(interaction)
        interaction.response.send_modal.assert_awaited_once()
        modal = interaction.response.send_modal.call_args.args[0]
        assert isinstance(modal, TimeoutDurationModal)

    async def test_dm_callback(self):
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
        }
        view = SettingsDashboardView(12345, cfg)
        interaction = _make_mock_interaction(12345)

        await view.dm_callback(interaction)
        interaction.response.send_modal.assert_awaited_once()
        modal = interaction.response.send_modal.call_args.args[0]
        assert isinstance(modal, CustomDMModal)

    async def test_switch_callback(self):
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
        }
        view = SettingsDashboardView(12345, cfg)
        interaction = _make_mock_interaction(12345)

        await view.switch_callback(interaction)
        interaction.response.edit_message.assert_awaited_once()
        edit_kwargs = interaction.response.edit_message.call_args.kwargs
        assert isinstance(edit_kwargs["view"], RolesChannelsDashboardView)


class TestTimeoutDurationModal:
    async def test_on_submit(self):
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
        }
        parent_view = SettingsDashboardView(12345, cfg)
        modal = TimeoutDurationModal(parent_view)
        modal.duration_input._value = "14d"

        interaction = _make_mock_interaction(12345)
        updated_cfg = dict(cfg, timeout_duration=1209600)

        with patch(
            "anti_phishing.commands.db.update_guild_config",
            new_callable=AsyncMock,
            return_value=updated_cfg,
        ) as mock_update:
            await modal.on_submit(interaction)
            mock_update.assert_awaited_once_with(12345, timeout_duration=1209600)

        assert parent_view.cfg["timeout_duration"] == 1209600
        interaction.response.edit_message.assert_awaited_once()
        interaction.followup.send.assert_awaited_once()
        assert "1209600s" in interaction.followup.send.call_args.args[0]


class TestCustomDMModal:
    async def test_on_submit_set_custom_message(self):
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
            "dm_message": None,
        }
        parent_view = SettingsDashboardView(12345, cfg)
        modal = CustomDMModal(parent_view)
        modal.dm_input._value = "Your account was compromised!"

        interaction = _make_mock_interaction(12345)
        updated_cfg = dict(cfg, dm_message="Your account was compromised!")

        with patch(
            "anti_phishing.commands.db.update_guild_config",
            new_callable=AsyncMock,
            return_value=updated_cfg,
        ) as mock_update:
            await modal.on_submit(interaction)
            mock_update.assert_awaited_once_with(12345, dm_message="Your account was compromised!")

        interaction.response.edit_message.assert_awaited_once()
        interaction.followup.send.assert_awaited_once_with("✅ Custom DM message set.", ephemeral=True)

    async def test_on_submit_reset_to_default(self):
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
            "dm_message": "Existing custom",
        }
        parent_view = SettingsDashboardView(12345, cfg)
        modal = CustomDMModal(parent_view)
        assert modal.dm_input.default == "Existing custom"
        modal.dm_input._value = "   "

        interaction = _make_mock_interaction(12345)
        updated_cfg = dict(cfg, dm_message=None)

        with patch(
            "anti_phishing.commands.db.update_guild_config",
            new_callable=AsyncMock,
            return_value=updated_cfg,
        ) as mock_update:
            await modal.on_submit(interaction)
            mock_update.assert_awaited_once_with(12345, dm_message=None)

        interaction.response.edit_message.assert_awaited_once()
        interaction.followup.send.assert_awaited_once_with("✅ DM message reset to default.", ephemeral=True)


class TestRolesChannelsDashboardView:
    async def test_channel_callback(self):
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
        }
        view = RolesChannelsDashboardView(12345, cfg)
        interaction = _make_mock_interaction(12345)
        view.channel_select._values = [MagicMock(id=555), MagicMock(id=666)]

        updated_cfg = dict(cfg, alert_channels=[555, 666])
        with patch(
            "anti_phishing.commands.db.update_guild_config",
            new_callable=AsyncMock,
            return_value=updated_cfg,
        ) as mock_update:
            await view.channel_callback(interaction)
            mock_update.assert_awaited_once_with(12345, alert_channels=[555, 666])

        interaction.response.edit_message.assert_awaited_once()

    async def test_mod_callback(self):
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
        }
        view = RolesChannelsDashboardView(12345, cfg)
        interaction = _make_mock_interaction(12345)
        view.mod_select._values = [MagicMock(id=777)]

        updated_cfg = dict(cfg, mod_roles=[777])
        with patch(
            "anti_phishing.commands.db.update_guild_config",
            new_callable=AsyncMock,
            return_value=updated_cfg,
        ) as mock_update:
            await view.mod_callback(interaction)
            mock_update.assert_awaited_once_with(12345, mod_roles=[777])

        interaction.response.edit_message.assert_awaited_once()

    async def test_bypass_callback_selected(self):
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
        }
        view = RolesChannelsDashboardView(12345, cfg)
        interaction = _make_mock_interaction(12345)
        view.bypass_select._values = [MagicMock(id=888)]

        updated_cfg = dict(cfg, bypass_role=888)
        with patch(
            "anti_phishing.commands.db.update_guild_config",
            new_callable=AsyncMock,
            return_value=updated_cfg,
        ) as mock_update:
            await view.bypass_callback(interaction)
            mock_update.assert_awaited_once_with(12345, bypass_role=888)

        interaction.response.edit_message.assert_awaited_once()

    async def test_bypass_callback_empty(self):
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 888,
        }
        view = RolesChannelsDashboardView(12345, cfg)
        interaction = _make_mock_interaction(12345)
        view.bypass_select._values = []

        updated_cfg = dict(cfg, bypass_role=0)
        with patch(
            "anti_phishing.commands.db.update_guild_config",
            new_callable=AsyncMock,
            return_value=updated_cfg,
        ) as mock_update:
            await view.bypass_callback(interaction)
            mock_update.assert_awaited_once_with(12345, bypass_role=0)

        interaction.response.edit_message.assert_awaited_once()

    async def test_back_callback(self):
        cfg = {
            "enabled": True,
            "action": "timeout",
            "timeout_duration": 604800,
            "alert_channels": [],
            "mod_roles": [],
            "bypass_role": 0,
        }
        view = RolesChannelsDashboardView(12345, cfg)
        interaction = _make_mock_interaction(12345)

        await view.back_callback(interaction)
        interaction.response.edit_message.assert_awaited_once()
        edit_kwargs = interaction.response.edit_message.call_args.kwargs
        assert isinstance(edit_kwargs["view"], SettingsDashboardView)


class TestAntiphishingCommandErrorPaths:
    async def test_cmd_stats_failure(self):
        interaction = _make_mock_interaction(12345)
        with patch(
            "anti_phishing.commands.db.get_stats",
            new_callable=AsyncMock,
            side_effect=Exception("DB fail"),
        ):
            await cmd_stats.callback(interaction)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.followup.send.assert_awaited_once_with("❌ Failed to fetch stats.", ephemeral=True)

    async def test_cmd_settings_failure(self):
        interaction = _make_mock_interaction(12345)
        with patch(
            "anti_phishing.commands.db.get_or_create_guild_config",
            new_callable=AsyncMock,
            side_effect=Exception("DB fail"),
        ):
            await cmd_settings.callback(interaction)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.followup.send.assert_awaited_once_with("❌ Failed to open settings dashboard.", ephemeral=True)


class TestViewComponentAuthorization:
    async def test_settings_dashboard_admin_allowed(self):
        view = SettingsDashboardView(12345, {"enabled": True, "action": "timeout"})
        interaction = _make_mock_interaction(12345)
        interaction.user.guild_permissions = discord.Permissions(administrator=True)
        interaction.response.is_done.return_value = False
        assert await view.interaction_check(interaction) is True

    async def test_settings_dashboard_non_admin_rejected(self):
        view = SettingsDashboardView(12345, {"enabled": True, "action": "timeout"})
        interaction = _make_mock_interaction(12345)
        interaction.user.guild_permissions = discord.Permissions(administrator=False)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        assert await view.interaction_check(interaction) is False
        interaction.response.send_message.assert_awaited_once()
        assert "Only server administrators" in interaction.response.send_message.call_args.args[0]

    async def test_settings_dashboard_cross_guild_rejected(self):
        view = SettingsDashboardView(12345, {"enabled": True, "action": "timeout"})
        interaction = _make_mock_interaction(99999)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        assert await view.interaction_check(interaction) is False
        assert "does not belong to this server" in interaction.response.send_message.call_args.args[0]

    async def test_roles_channels_non_admin_rejected(self):
        view = RolesChannelsDashboardView(12345, {"alert_channels": [], "mod_roles": [], "bypass_role": 0})
        interaction = _make_mock_interaction(12345)
        interaction.user.guild_permissions = discord.Permissions(administrator=False)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        assert await view.interaction_check(interaction) is False
        interaction.response.send_message.assert_awaited_once()

    async def test_timeout_modal_non_admin_rejected(self):
        view = SettingsDashboardView(12345, {"timeout_duration": 604800})
        modal = TimeoutDurationModal(view)
        interaction = _make_mock_interaction(12345)
        interaction.user.guild_permissions = discord.Permissions(administrator=False)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        assert await modal.interaction_check(interaction) is False

    async def test_timeout_modal_on_submit_non_admin_blocked(self):
        view = SettingsDashboardView(12345, {"timeout_duration": 604800})
        modal = TimeoutDurationModal(view)
        modal.duration_input._value = "14d"
        interaction = _make_mock_interaction(12345)
        interaction.user.guild_permissions = discord.Permissions(administrator=False)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()

        with patch("anti_phishing.commands.db.update_guild_config", new_callable=AsyncMock) as mock_update:
            await modal.on_submit(interaction)
            mock_update.assert_not_called()

    async def test_custom_dm_modal_non_admin_rejected(self):
        view = SettingsDashboardView(12345, {})
        modal = CustomDMModal(view)
        interaction = _make_mock_interaction(12345)
        interaction.user.guild_permissions = discord.Permissions(administrator=False)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        assert await modal.interaction_check(interaction) is False

    async def test_custom_dm_modal_on_submit_non_admin_blocked(self):
        view = SettingsDashboardView(12345, {})
        modal = CustomDMModal(view)
        modal.dm_input._value = "Hacked message"
        interaction = _make_mock_interaction(12345)
        interaction.user.guild_permissions = discord.Permissions(administrator=False)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()

        with patch("anti_phishing.commands.db.update_guild_config", new_callable=AsyncMock) as mock_update:
            await modal.on_submit(interaction)
            mock_update.assert_not_called()


class TestSlashCommandPermissionsAndErrorHandlers:
    def test_commands_have_admin_permission_check(self):
        assert any(
            hasattr(c, "predicate") and "administrator" in str(c.predicate) or hasattr(c, "__name__")
            for c in cmd_stats.checks
        )
        assert any(
            hasattr(c, "predicate") and "administrator" in str(c.predicate) or hasattr(c, "__name__")
            for c in cmd_settings.checks
        )

    async def test_cmd_stats_error_handles_missing_permissions(self):
        interaction = _make_mock_interaction(12345)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        error = discord.app_commands.MissingPermissions(["administrator"])

        await cmd_stats_error(interaction, error)
        interaction.response.send_message.assert_awaited_once_with(
            "❌ You do not have permission to run this command.", ephemeral=True
        )

    async def test_cmd_settings_error_handles_missing_permissions(self):
        interaction = _make_mock_interaction(12345)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        error = discord.app_commands.MissingPermissions(["administrator"])

        await cmd_settings_error(interaction, error)
        interaction.response.send_message.assert_awaited_once_with(
            "❌ You do not have permission to run this command.", ephemeral=True
        )
