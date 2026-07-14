import logging

import discord
from discord import app_commands

import db

logger = logging.getLogger("discord")


def _format_duration(seconds: int) -> str:
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if not days and minutes:
        parts.append(f"{minutes}m")
    if not days and not hours and secs:
        parts.append(f"{secs}s")
    return " ".join(parts) if parts else "0s"


def _build_settings_embed(guild: discord.Guild, cfg: dict) -> discord.Embed:
    alert_chs = ", ".join(f"<#{c}>" for c in cfg["alert_channels"]) or "none"
    mod_roles = ", ".join(f"<@&{r}>" for r in cfg["mod_roles"]) or "none"
    bypass = f"<@&{cfg['bypass_role']}>" if cfg["bypass_role"] else "none"

    embed = discord.Embed(title=f"🛡️ Anti-Phishing Settings — {guild.name}", color=discord.Color.blurple())
    embed.add_field(name="Status", value="🟢 Enabled" if cfg["enabled"] else "🔴 Disabled", inline=True)
    embed.add_field(name="Action", value=cfg["action"].capitalize(), inline=True)
    if cfg["action"] == "timeout":
        embed.add_field(name="Timeout Duration", value=_format_duration(cfg["timeout_duration"]), inline=True)
    embed.add_field(name="Alert Channels", value=alert_chs, inline=False)
    embed.add_field(name="Mod Roles", value=mod_roles, inline=False)
    embed.add_field(name="Bypass Role", value=bypass, inline=False)

    dm_msg = cfg.get("dm_message")
    if dm_msg:
        if len(dm_msg) > 100:
            dm_msg = f"{dm_msg[:97]}..."
    else:
        dm_msg = "Default"
    embed.add_field(name="Custom DM Message", value=dm_msg, inline=False)

    embed.set_footer(text="Use the components below to configure settings. Ephemeral session expires in 3 mins.")
    return embed


class TimeoutDurationModal(discord.ui.Modal, title="Set Timeout Duration"):
    duration_input = discord.ui.TextInput(
        label="Duration (e.g. 7d, 28d, or seconds)",
        placeholder="7d",
        required=True,
        max_length=20,
    )

    def __init__(self, parent_view: "SettingsDashboardView"):
        super().__init__()
        self.parent_view = parent_view
        self.duration_input.default = _format_duration(parent_view.cfg.get("timeout_duration", 604800))

    async def on_submit(self, interaction: discord.Interaction):
        from anti_phishing.actions import _parse_duration

        duration_str = self.duration_input.value.strip()
        secs = _parse_duration(duration_str)

        self.parent_view.cfg = await db.update_guild_config(interaction.guild_id, timeout_duration=secs)
        embed = _build_settings_embed(interaction.guild, self.parent_view.cfg)
        await interaction.response.edit_message(embed=embed, view=self.parent_view)
        await interaction.followup.send(f"✅ Timeout duration set to **{secs}s** ({duration_str}).", ephemeral=True)


class CustomDMModal(discord.ui.Modal, title="Set Custom DM Message"):
    dm_input = discord.ui.TextInput(
        label="DM message (leave blank to reset to default)",
        style=discord.TextStyle.paragraph,
        placeholder="Your account has been sending phishing messages...",
        required=False,
        max_length=1000,
    )

    def __init__(self, parent_view: "SettingsDashboardView"):
        super().__init__()
        self.parent_view = parent_view
        current_msg = parent_view.cfg.get("dm_message")
        if current_msg:
            self.dm_input.default = current_msg

    async def on_submit(self, interaction: discord.Interaction):
        value = self.dm_input.value.strip() or None
        self.parent_view.cfg = await db.update_guild_config(interaction.guild_id, dm_message=value)
        embed = _build_settings_embed(interaction.guild, self.parent_view.cfg)
        await interaction.response.edit_message(embed=embed, view=self.parent_view)
        if value:
            await interaction.followup.send("✅ Custom DM message set.", ephemeral=True)
        else:
            await interaction.followup.send("✅ DM message reset to default.", ephemeral=True)


class SettingsDashboardView(discord.ui.View):
    def __init__(self, guild_id: int, cfg: dict):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.cfg = cfg

        enabled = cfg.get("enabled", True)
        self.toggle_btn = discord.ui.Button(
            label="Disable Anti-Phishing" if enabled else "Enable Anti-Phishing",
            style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
            custom_id="toggle_bot",
            row=0,
        )
        self.toggle_btn.callback = self.toggle_callback
        self.add_item(self.toggle_btn)

        self.action_select = discord.ui.Select(
            placeholder="Select Punishment Action...",
            options=[
                discord.SelectOption(
                    label="Timeout",
                    value="timeout",
                    description="Timeout the member",
                    default=(cfg["action"] == "timeout"),
                ),
                discord.SelectOption(
                    label="Kick",
                    value="kick",
                    description="Kick the member",
                    default=(cfg["action"] == "kick"),
                ),
                discord.SelectOption(
                    label="Ban",
                    value="ban",
                    description="Ban the member",
                    default=(cfg["action"] == "ban"),
                ),
                discord.SelectOption(
                    label="Warn",
                    value="warn",
                    description="DM only, no guild action",
                    default=(cfg["action"] == "warn"),
                ),
            ],
            custom_id="action_select",
            row=1,
        )
        self.action_select.callback = self.action_callback
        self.add_item(self.action_select)

        if cfg["action"] == "timeout":
            self.timeout_btn = discord.ui.Button(
                label="Set Timeout Duration", style=discord.ButtonStyle.secondary, custom_id="set_timeout", row=2
            )
            self.timeout_btn.callback = self.timeout_callback
            self.add_item(self.timeout_btn)

        self.dm_btn = discord.ui.Button(
            label="Set Custom DM Message", style=discord.ButtonStyle.secondary, custom_id="set_dm", row=2
        )
        self.dm_btn.callback = self.dm_callback
        self.add_item(self.dm_btn)

        self.switch_btn = discord.ui.Button(
            label="Roles & Channels ➡️", style=discord.ButtonStyle.primary, custom_id="switch_page", row=3
        )
        self.switch_btn.callback = self.switch_callback
        self.add_item(self.switch_btn)

    async def toggle_callback(self, interaction: discord.Interaction):
        new_val = not self.cfg.get("enabled", True)
        self.cfg = await db.update_guild_config(interaction.guild_id, enabled=new_val)
        embed = _build_settings_embed(interaction.guild, self.cfg)
        self.toggle_btn.label = "Disable Anti-Phishing" if new_val else "Enable Anti-Phishing"
        self.toggle_btn.style = discord.ButtonStyle.danger if new_val else discord.ButtonStyle.success
        await interaction.response.edit_message(embed=embed, view=self)

    async def action_callback(self, interaction: discord.Interaction):
        selected_action = self.action_select.values[0]
        self.cfg = await db.update_guild_config(interaction.guild_id, action=selected_action)

        embed = _build_settings_embed(interaction.guild, self.cfg)
        view = SettingsDashboardView(self.guild_id, self.cfg)
        await interaction.response.edit_message(embed=embed, view=view)

    async def timeout_callback(self, interaction: discord.Interaction):
        modal = TimeoutDurationModal(self)
        await interaction.response.send_modal(modal)

    async def dm_callback(self, interaction: discord.Interaction):
        modal = CustomDMModal(self)
        await interaction.response.send_modal(modal)

    async def switch_callback(self, interaction: discord.Interaction):
        view = RolesChannelsDashboardView(self.guild_id, self.cfg)
        embed = _build_settings_embed(interaction.guild, self.cfg)
        embed.set_footer(text="Manage roles & channels configuration. Ephemeral session expires in 3 mins.")
        await interaction.response.edit_message(embed=embed, view=view)


class RolesChannelsDashboardView(discord.ui.View):
    def __init__(self, guild_id: int, cfg: dict):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.cfg = cfg

        self.channel_select = discord.ui.ChannelSelect(
            placeholder="Select Alert Channels...",
            channel_types=[discord.ChannelType.text],
            min_values=0,
            max_values=5,
            custom_id="channel_select",
            row=0,
        )
        self.channel_select.callback = self.channel_callback
        self.add_item(self.channel_select)

        self.mod_select = discord.ui.RoleSelect(
            placeholder="Select Mod Ping Roles...", min_values=0, max_values=5, custom_id="mod_select", row=1
        )
        self.mod_select.callback = self.mod_callback
        self.add_item(self.mod_select)

        self.bypass_select = discord.ui.RoleSelect(
            placeholder="Select Bypass Role...", min_values=0, max_values=1, custom_id="bypass_select", row=2
        )
        self.bypass_select.callback = self.bypass_callback
        self.add_item(self.bypass_select)

        self.back_btn = discord.ui.Button(
            label="⬅️ Back to Main", style=discord.ButtonStyle.primary, custom_id="back_to_main", row=3
        )
        self.back_btn.callback = self.back_callback
        self.add_item(self.back_btn)

    async def channel_callback(self, interaction: discord.Interaction):
        selected_ids = [ch.id for ch in self.channel_select.values]
        self.cfg = await db.update_guild_config(interaction.guild_id, alert_channels=selected_ids)
        embed = _build_settings_embed(interaction.guild, self.cfg)
        await interaction.response.edit_message(embed=embed, view=self)

    async def mod_callback(self, interaction: discord.Interaction):
        selected_ids = [r.id for r in self.mod_select.values]
        self.cfg = await db.update_guild_config(interaction.guild_id, mod_roles=selected_ids)
        embed = _build_settings_embed(interaction.guild, self.cfg)
        await interaction.response.edit_message(embed=embed, view=self)

    async def bypass_callback(self, interaction: discord.Interaction):
        selected_id = self.bypass_select.values[0].id if self.bypass_select.values else 0
        self.cfg = await db.update_guild_config(interaction.guild_id, bypass_role=selected_id)
        embed = _build_settings_embed(interaction.guild, self.cfg)
        await interaction.response.edit_message(embed=embed, view=self)

    async def back_callback(self, interaction: discord.Interaction):
        view = SettingsDashboardView(self.guild_id, self.cfg)
        embed = _build_settings_embed(interaction.guild, self.cfg)
        await interaction.response.edit_message(embed=embed, view=view)


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------

antiphishing = app_commands.Group(
    name="antiphishing",
    description="Anti-phishing settings for this server",
    default_permissions=discord.Permissions(administrator=True),
    guild_only=True,
)

# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


@antiphishing.command(name="stats", description="Show detection stats for this server")
async def cmd_stats(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        stats = await db.get_stats(interaction.guild_id)
    except Exception as exc:
        logger.exception("antiphishing stats failed: %s", exc)
        await interaction.followup.send("❌ Failed to fetch stats.", ephemeral=True)
        return

    embed = discord.Embed(title="Anti-Phishing Stats", color=discord.Color.blurple())
    embed.add_field(name="Total detections", value=str(stats["total"]), inline=False)

    if stats["top"]:
        top_str = "\n".join(f"`{e['domain']}` — {e['count']}x" for e in stats["top"])
        embed.add_field(name="Top blocked domains", value=top_str, inline=False)

    if stats["last"]:
        last = stats["last"]
        embed.add_field(
            name="Last detection",
            value=f"`{last['domain']}` ({last['reason']}) at {last['timestamp']}",
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@antiphishing.command(name="settings", description="Open interactive anti-phishing settings dashboard")
async def cmd_settings(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        cfg = await db.get_or_create_guild_config(interaction.guild_id)
        embed = _build_settings_embed(interaction.guild, cfg)
        view = SettingsDashboardView(interaction.guild_id, cfg)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception as exc:
        logger.exception("antiphishing settings failed: %s", exc)
        await interaction.followup.send("❌ Failed to open settings dashboard.", ephemeral=True)
