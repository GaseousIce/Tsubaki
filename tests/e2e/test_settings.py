"""Tier 1: Feature Coverage — Anti-Phishing Settings Dashboard.

Covers at least 5 test cases testing interactive settings dashboard,
toggle enabled/disabled, action selection, modal submission, and pagination.
"""

import db

from .helpers import create_admin_member


class TestTier1SettingsFeature:
    """Opaque-box feature coverage for /antiphishing settings dashboard."""

    async def test_settings_command_displays_dashboard_embed(self, simcord_env):
        """Admin invokes /antiphishing settings and receives dashboard embed and UI components."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("admin-chat")
        admin = create_admin_member(simcord_env, guild, "admin")

        result = await admin.slash(channel, "antiphishing settings")

        assert result.followups
        followup = result.followups[0]
        assert followup.ephemeral is True
        assert len(followup.embeds) == 1

        embed = followup.embeds[0]
        assert "Anti-Phishing Settings" in embed.title
        field_map = {f.name: f.value for f in embed.fields}
        assert field_map["Status"] == "🟢 Enabled"
        assert field_map["Action"] == "Timeout"

    async def test_settings_toggle_enable_disable(self, simcord_env):
        """Admin toggles bot status off and on via toggle button, updating database state."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("admin-chat")
        admin = create_admin_member(simcord_env, guild, "admin")

        result = await admin.slash(channel, "antiphishing settings")
        dashboard_msg = result.followups[0]

        # 1. Click toggle button to Disable
        click1 = await admin.click(dashboard_msg, custom_id="toggle_bot")
        fields1 = {f.name: f.value for f in click1.response.embeds[0].fields}
        assert fields1["Status"] == "🔴 Disabled"

        # Verify DB is updated
        cfg1 = await db.get_guild_config(guild.id)
        assert cfg1["enabled"] is False

        # 2. Click toggle button to Re-enable
        click2 = await admin.click(click1.response, custom_id="toggle_bot")
        fields2 = {f.name: f.value for f in click2.response.embeds[0].fields}
        assert fields2["Status"] == "🟢 Enabled"

        cfg2 = await db.get_guild_config(guild.id)
        assert cfg2["enabled"] is True

    async def test_settings_action_select_menu(self, simcord_env):
        """Admin selects 'kick' from the action select menu; configuration and UI update."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("admin-chat")
        admin = create_admin_member(simcord_env, guild, "admin")

        result = await admin.slash(channel, "antiphishing settings")
        dashboard_msg = result.followups[0]

        select_res = await admin.select(dashboard_msg, ["kick"], custom_id="action_select")
        fields = {f.name: f.value for f in select_res.response.embeds[0].fields}
        assert fields["Action"] == "Kick"

        # Verify database updated
        cfg = await db.get_guild_config(guild.id)
        assert cfg["action"] == "kick"

    async def test_settings_timeout_modal_submission(self, simcord_env):
        """Admin opens and submits TimeoutDurationModal, setting a new duration."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("admin-chat")
        admin = create_admin_member(simcord_env, guild, "admin")

        result = await admin.slash(channel, "antiphishing settings")
        dashboard_msg = result.followups[0]

        modal_prompt = await admin.click(dashboard_msg, custom_id="set_timeout")
        assert modal_prompt.modal is not None
        assert modal_prompt.modal["title"] == "Set Timeout Duration"

        input_cid = modal_prompt.modal["components"][0]["components"][0]["custom_id"]
        modal_sub = await admin.submit_modal(modal_prompt, {input_cid: "14d"})

        assert modal_sub.followups
        assert "1209600s" in modal_sub.followups[0].content

        # Verify database updated with 14 days in seconds
        cfg = await db.get_guild_config(guild.id)
        assert cfg["timeout_duration"] == 1209600

    async def test_settings_custom_dm_modal_submission(self, simcord_env):
        """Admin opens and submits CustomDMModal, updating the user recovery DM message."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("admin-chat")
        admin = create_admin_member(simcord_env, guild, "admin")

        result = await admin.slash(channel, "antiphishing settings")
        dashboard_msg = result.followups[0]

        modal_prompt = await admin.click(dashboard_msg, custom_id="set_dm")
        assert modal_prompt.modal is not None
        assert modal_prompt.modal["title"] == "Set Custom DM Message"

        input_cid = modal_prompt.modal["components"][0]["components"][0]["custom_id"]
        custom_text = "Security warning: please change your Discord credentials immediately!"
        modal_sub = await admin.submit_modal(modal_prompt, {input_cid: custom_text})

        assert modal_sub.followups
        assert "Custom DM message set" in modal_sub.followups[0].content

        cfg = await db.get_guild_config(guild.id)
        assert cfg["dm_message"] == custom_text

    async def test_settings_pagination_switching(self, simcord_env):
        """Admin switches between main settings dashboard and roles/channels configuration page."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("admin-chat")
        admin = create_admin_member(simcord_env, guild, "admin")

        result = await admin.slash(channel, "antiphishing settings")
        page1 = result.followups[0]

        # Switch to Page 2 (Roles & Channels)
        switch_to_p2 = await admin.click(page1, custom_id="switch_page")
        footer_text = switch_to_p2.response.embeds[0].footer.text
        assert "Manage roles & channels" in footer_text

        # Switch back to Page 1 via Back button
        switch_to_p1 = await admin.click(switch_to_p2.response, custom_id="back_to_main")
        p1_footer = switch_to_p1.response.embeds[0].footer.text
        assert "Use the components below" in p1_footer
