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
            ("notanumberd", 604800),
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
        message.content = ""
        message.attachments = []
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

    async def test_member_not_found_still_deletes_message_and_alerts(self, mock_db):
        message = self._make_mock_message()
        message.guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(), "not found"))
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        message.guild.get_channel = MagicMock(return_value=mock_channel)
        guild_cfg = {"action": "timeout", "alert_channels": [789]}

        with patch("anti_phishing.actions.db.log_detection", new_callable=AsyncMock) as mock_log:
            await handle_detection(message, None, guild_cfg, "https://evil.com", "official_blacklist")
            mock_log.assert_awaited_once()

        message.guild.fetch_member.assert_awaited_once_with(456)
        message.delete.assert_awaited_once()
        mock_channel.send.assert_awaited_once()

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

    async def test_alert_channel_with_content_and_attachment_metadata(self, mock_db):
        message = self._make_mock_message()
        message.content = "Look at this free promo!"
        mock_att = MagicMock(spec=discord.Attachment)
        mock_att.filename = "promo.png"
        mock_att.url = "https://cdn.discordapp.com/promo.png"
        mock_att.size = 1024
        mock_att.read = AsyncMock()
        mock_att.to_file = AsyncMock()
        message.attachments = [mock_att]

        member = self._make_mock_member()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        message.guild.get_channel = MagicMock(return_value=mock_channel)

        guild_cfg = {"action": "timeout", "alert_channels": [789]}

        with patch("anti_phishing.actions.db.log_detection", new_callable=AsyncMock) as mock_log:
            await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")
            mock_log.assert_awaited_once_with(
                123,
                "https://evil.com",
                "official_blacklist",
                content="Look at this free promo!",
                attachments=["https://cdn.discordapp.com/promo.png"],
            )

        # Verify NO downloads occur
        mock_att.read.assert_not_called()
        mock_att.to_file.assert_not_called()

        mock_channel.send.assert_awaited_once()
        kwargs = mock_channel.send.call_args.kwargs
        assert "files" not in kwargs
        embed = kwargs["embed"]
        fields = {f.name: f.value for f in embed.fields}
        assert "Message Content" in fields
        assert fields["Message Content"] == "Look at this free promo!"
        assert "Attachments (1)" in fields
        assert "promo.png" in fields["Attachments (1)"]
        assert "https://cdn.discordapp.com/promo.png" in fields["Attachments (1)"]

    async def test_alert_channel_image_attachment_sets_embed_image_without_download(self, mock_db):
        message = self._make_mock_message()
        message.content = ""
        mock_att = MagicMock(spec=discord.Attachment)
        mock_att.filename = "screenshot.jpg"
        mock_att.url = "https://cdn.discordapp.com/screenshot.jpg"
        mock_att.size = 1024
        mock_att.read = AsyncMock()
        mock_att.to_file = AsyncMock()
        message.attachments = [mock_att]

        member = self._make_mock_member()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        message.guild.get_channel = MagicMock(return_value=mock_channel)

        guild_cfg = {"action": "timeout", "alert_channels": [789]}
        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        # Verify NO downloads occur
        mock_att.read.assert_not_called()
        mock_att.to_file.assert_not_called()

        mock_channel.send.assert_awaited_once()
        kwargs = mock_channel.send.call_args.kwargs
        assert "files" not in kwargs
        embed = kwargs["embed"]
        assert embed.image.url == "https://cdn.discordapp.com/screenshot.jpg"
        fields = {f.name: f.value for f in embed.fields}
        assert fields["Message Content"] == "*(No text content)*"

    async def test_alert_channel_with_embeds(self, mock_db):
        message = self._make_mock_message()
        message.content = ""
        message.attachments = []

        fake_embed = MagicMock(spec=discord.Embed)
        fake_embed.title = "Scam Nitro Gift"
        fake_embed.description = "Click here to claim: https://nitro-scam.xyz"
        fake_embed.url = "https://nitro-scam.xyz"
        fake_embed.fields = []
        fake_embed.image = MagicMock(url="https://scam.xyz/banner.png")
        fake_embed.thumbnail = None
        message.embeds = [fake_embed]

        member = self._make_mock_member()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        message.guild.get_channel = MagicMock(return_value=mock_channel)

        guild_cfg = {"action": "timeout", "alert_channels": [789]}

        with patch("anti_phishing.actions.db.log_detection", new_callable=AsyncMock) as mock_log:
            await handle_detection(message, member, guild_cfg, "https://nitro-scam.xyz", "official_blacklist")
            mock_log.assert_awaited_once()
            args, kwargs = mock_log.call_args
            assert "Scam Nitro Gift" in kwargs["content"]
            assert "https://scam.xyz/banner.png" in kwargs["attachments"]

        mock_channel.send.assert_awaited_once()
        kwargs = mock_channel.send.call_args.kwargs
        embed = kwargs["embed"]
        assert embed.image.url == "https://scam.xyz/banner.png"
        fields = {f.name: f.value for f in embed.fields}
        assert fields["Message Content"] == "*(Content in Embeds below)*"
        assert "Original Embeds (1)" in fields
        assert "Scam Nitro Gift" in fields["Original Embeds (1)"]

    async def test_timeout_forbidden_continues(self, mock_db):
        message = self._make_mock_message()
        member = self._make_mock_member()
        member.timeout.side_effect = discord.Forbidden(MagicMock(), "no perm")
        guild_cfg = {"action": "timeout", "alert_channels": []}

        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")
        message.delete.assert_awaited_once()

    async def test_kick_forbidden_continues(self, mock_db):
        message = self._make_mock_message()
        member = self._make_mock_member()
        member.kick.side_effect = discord.Forbidden(MagicMock(), "no perm")
        guild_cfg = {"action": "kick", "alert_channels": []}

        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")
        message.delete.assert_awaited_once()

    async def test_ban_forbidden_continues(self, mock_db):
        message = self._make_mock_message()
        member = self._make_mock_member()
        member.ban.side_effect = discord.Forbidden(MagicMock(), "no perm")
        guild_cfg = {"action": "ban", "alert_channels": []}

        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")
        message.delete.assert_awaited_once()

    async def test_alert_with_mod_roles_and_many_attachments_and_long_embed(self, mock_db):
        message = self._make_mock_message()
        message.content = ""
        # 7 attachments
        attachments = []
        for i in range(7):
            att = MagicMock(spec=discord.Attachment)
            att.filename = f"file{i}.png"
            att.url = f"https://cdn.discordapp.com/file{i}.png"
            attachments.append(att)
        message.attachments = attachments

        fake_embed = MagicMock(spec=discord.Embed)
        fake_embed.title = "A" * 600
        fake_embed.description = "B" * 600
        fake_embed.url = None
        fake_embed.fields = []
        fake_embed.image = None
        fake_embed.thumbnail = None
        message.embeds = [fake_embed]

        member = self._make_mock_member()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        message.guild.get_channel = MagicMock(return_value=mock_channel)

        guild_cfg = {"action": "warn", "alert_channels": [789], "mod_roles": [111, 222]}
        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        mock_channel.send.assert_awaited_once()
        call_kwargs = mock_channel.send.call_args.kwargs
        assert call_kwargs["content"] == "<@&111> <@&222>"
        embeds = call_kwargs.get("embeds")
        embed = embeds[0] if embeds else call_kwargs["embed"]
        if embeds:
            assert len(embeds) == 4
            assert all(e.url == embeds[0].url for e in embeds)
            for i, e in enumerate(embeds):
                assert e.image.url == f"https://cdn.discordapp.com/file{i}.png"
        fields = {f.name: f.value for f in embed.fields}
        assert "Attachments (7)" in fields
        assert "*(and 2 more)*" in fields["Attachments (7)"]
        assert fields["Original Embeds (1)"].endswith("...")

    async def test_alert_channel_send_forbidden_continues(self, mock_db):
        message = self._make_mock_message()
        member = self._make_mock_member()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no access"))
        message.guild.get_channel = MagicMock(return_value=mock_channel)

        guild_cfg = {"action": "timeout", "alert_channels": [789]}
        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")
        message.delete.assert_awaited_once()

    async def test_alert_with_extra_long_attachment_urls_truncated(self, mock_db):
        message = self._make_mock_message()
        message.content = "check this"
        attachments = []
        for i in range(5):
            att = MagicMock(spec=discord.Attachment)
            att.filename = f"long_file_name_evidence_{i}.png"
            att.url = f"https://cdn.discordapp.com/attachments/12345/67890/{'x' * 250}_{i}.png"
            attachments.append(att)
        message.attachments = attachments

        member = self._make_mock_member()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        message.guild.get_channel = MagicMock(return_value=mock_channel)

        guild_cfg = {"action": "warn", "alert_channels": [789]}
        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        mock_channel.send.assert_awaited_once()
        embeds = mock_channel.send.call_args.kwargs.get("embeds")
        embed = embeds[0] if embeds else mock_channel.send.call_args.kwargs["embed"]
        if embeds:
            assert len(embeds) == 4
        fields = {f.name: f.value for f in embed.fields}
        assert "Attachments (5)" in fields
        assert len(fields["Attachments (5)"]) <= 1024
        assert fields["Attachments (5)"].endswith("...")

    async def test_alert_channel_large_attachments_metadata_only(self, mock_db):
        message = self._make_mock_message()
        message.content = "payloads"
        att1 = MagicMock(spec=discord.Attachment)
        att1.filename = "file1.png"
        att1.url = "https://cdn.discordapp.com/file1.png"
        att1.size = 25 * 1024 * 1024
        att1.read = AsyncMock()
        att1.to_file = AsyncMock()

        att2 = MagicMock(spec=discord.Attachment)
        att2.filename = "file2.png"
        att2.url = "https://cdn.discordapp.com/file2.png"
        att2.size = 50 * 1024 * 1024
        att2.read = AsyncMock()
        att2.to_file = AsyncMock()

        message.attachments = [att1, att2]

        member = self._make_mock_member()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        message.guild.get_channel = MagicMock(return_value=mock_channel)

        guild_cfg = {"action": "timeout", "alert_channels": [789]}
        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        # No download attempts made
        att1.read.assert_not_called()
        att1.to_file.assert_not_called()
        att2.read.assert_not_called()
        att2.to_file.assert_not_called()

        mock_channel.send.assert_awaited_once()
        assert "files" not in mock_channel.send.call_args.kwargs
        embeds = mock_channel.send.call_args.kwargs.get("embeds")
        embed = embeds[0] if embeds else mock_channel.send.call_args.kwargs["embed"]
        if embeds:
            assert len(embeds) == 2
            assert embeds[0].image.url == "https://cdn.discordapp.com/file1.png"
            assert embeds[1].image.url == "https://cdn.discordapp.com/file2.png"
            assert embeds[0].url == embeds[1].url
        fields = {f.name: f.value for f in embed.fields}
        assert "Attachments (2)" in fields
        assert "file1.png" in fields["Attachments (2)"]
        assert "file2.png" in fields["Attachments (2)"]

    async def test_alert_channel_http_exception_logged(self, mock_db):
        message = self._make_mock_message()
        member = self._make_mock_member()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock(
            side_effect=discord.HTTPException(MagicMock(status=500), "Discord Internal Error")
        )
        message.guild.get_channel = MagicMock(return_value=mock_channel)

        guild_cfg = {"action": "timeout", "alert_channels": [789]}
        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        mock_channel.send.assert_awaited_once()
        message.delete.assert_awaited_once()

    async def test_alert_multiple_channels_with_attachment_metadata(self, mock_db):
        message = self._make_mock_message()
        att = MagicMock(spec=discord.Attachment)
        att.filename = "test.png"
        att.url = "https://cdn.discordapp.com/test.png"
        att.size = 100
        att.read = AsyncMock()
        att.to_file = AsyncMock()
        message.attachments = [att]

        member = self._make_mock_member()
        channel1 = MagicMock(spec=discord.TextChannel)
        channel1.send = AsyncMock()
        channel2 = MagicMock(spec=discord.TextChannel)
        channel2.send = AsyncMock()

        def get_channel(ch_id):
            if ch_id == 111:
                return channel1
            if ch_id == 222:
                return channel2
            return None

        message.guild.get_channel = MagicMock(side_effect=get_channel)

        guild_cfg = {"action": "timeout", "alert_channels": [111, 222]}
        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        att.read.assert_not_called()
        att.to_file.assert_not_called()
        channel1.send.assert_awaited_once()
        channel2.send.assert_awaited_once()
        assert "files" not in channel1.send.call_args.kwargs
        assert "files" not in channel2.send.call_args.kwargs
        embed1 = channel1.send.call_args.kwargs["embed"]
        embed2 = channel2.send.call_args.kwargs["embed"]
        assert embed1.title == "⚠️ Phishing Detected"
        assert embed2.title == "⚠️ Phishing Detected"

    async def test_member_send_http_exception_continues_punishment_and_alert(self, mock_db):
        message = self._make_mock_message()
        member = self._make_mock_member()
        member.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=429), "Too Many Requests"))
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        message.guild.get_channel = MagicMock(return_value=mock_channel)

        guild_cfg = {"action": "timeout", "alert_channels": [789]}
        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        member.send.assert_awaited_once()
        member.timeout.assert_awaited_once()
        message.delete.assert_awaited_once()
        mock_channel.send.assert_awaited_once()

    async def test_alert_channel_attachment_grid_three_images(self, mock_db):
        message = self._make_mock_message()
        attachments = []
        for i in range(3):
            att = MagicMock(spec=discord.Attachment)
            att.filename = f"image_{i}.jpg"
            att.url = f"https://cdn.discordapp.com/image_{i}.jpg"
            attachments.append(att)
        message.attachments = attachments

        member = self._make_mock_member()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        message.guild.get_channel = MagicMock(return_value=mock_channel)

        guild_cfg = {"action": "timeout", "alert_channels": [789]}
        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        mock_channel.send.assert_awaited_once()
        embeds = mock_channel.send.call_args.kwargs["embeds"]
        assert len(embeds) == 3
        assert embeds[0].title == "⚠️ Phishing Detected"
        assert embeds[0].image.url == "https://cdn.discordapp.com/image_0.jpg"
        gallery_url = embeds[0].url
        assert gallery_url.startswith("https://discord.com")
        for i, emb in enumerate(embeds):
            assert emb.url == gallery_url
            assert emb.image.url == f"https://cdn.discordapp.com/image_{i}.jpg"

    async def test_alert_channel_attachment_grid_caps_at_four(self, mock_db):
        message = self._make_mock_message()
        attachments = []
        for i in range(6):
            att = MagicMock(spec=discord.Attachment)
            att.filename = f"pic_{i}.png"
            att.url = f"https://cdn.discordapp.com/pic_{i}.png"
            attachments.append(att)
        message.attachments = attachments

        member = self._make_mock_member()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        message.guild.get_channel = MagicMock(return_value=mock_channel)

        guild_cfg = {"action": "timeout", "alert_channels": [789]}
        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        mock_channel.send.assert_awaited_once()
        embeds = mock_channel.send.call_args.kwargs["embeds"]
        assert len(embeds) == 4
        gallery_url = embeds[0].url
        for i in range(4):
            assert embeds[i].url == gallery_url
            assert embeds[i].image.url == f"https://cdn.discordapp.com/pic_{i}.png"

    async def test_alert_channel_non_image_attachments_single_embed(self, mock_db):
        message = self._make_mock_message()
        att1 = MagicMock(spec=discord.Attachment)
        att1.filename = "script.py"
        att1.url = "https://cdn.discordapp.com/script.py"
        att2 = MagicMock(spec=discord.Attachment)
        att2.filename = "document.pdf"
        att2.url = "https://cdn.discordapp.com/document.pdf"
        message.attachments = [att1, att2]

        member = self._make_mock_member()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        message.guild.get_channel = MagicMock(return_value=mock_channel)

        guild_cfg = {"action": "timeout", "alert_channels": [789]}
        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        mock_channel.send.assert_awaited_once()
        assert "embeds" not in mock_channel.send.call_args.kwargs
        embed = mock_channel.send.call_args.kwargs["embed"]
        assert embed.image.url is None

    async def test_alert_channel_mixed_images_and_non_images(self, mock_db):
        message = self._make_mock_message()
        att1 = MagicMock(spec=discord.Attachment)
        att1.filename = "photo.png"
        att1.url = "https://cdn.discordapp.com/photo.png"
        att2 = MagicMock(spec=discord.Attachment)
        att2.filename = "archive.zip"
        att2.url = "https://cdn.discordapp.com/archive.zip"
        message.attachments = [att1, att2]

        member = self._make_mock_member()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        message.guild.get_channel = MagicMock(return_value=mock_channel)

        guild_cfg = {"action": "timeout", "alert_channels": [789]}
        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        mock_channel.send.assert_awaited_once()
        assert "embed" in mock_channel.send.call_args.kwargs
        embed = mock_channel.send.call_args.kwargs["embed"]
        assert embed.image.url == "https://cdn.discordapp.com/photo.png"

    async def test_alert_channel_fills_grid_from_embed_images(self, mock_db):
        message = self._make_mock_message()
        att = MagicMock(spec=discord.Attachment)
        att.filename = "evidence.png"
        att.url = "https://cdn.discordapp.com/evidence.png"
        message.attachments = [att]

        fake_embed = MagicMock(spec=discord.Embed)
        fake_embed.title = "Embed Title"
        fake_embed.description = "Embed Desc"
        fake_embed.url = None
        fake_embed.fields = []
        fake_embed.image = MagicMock(url="https://scam.xyz/banner1.png")
        fake_embed.thumbnail = None
        message.embeds = [fake_embed]

        member = self._make_mock_member()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        message.guild.get_channel = MagicMock(return_value=mock_channel)

        guild_cfg = {"action": "timeout", "alert_channels": [789]}
        await handle_detection(message, member, guild_cfg, "https://evil.com", "official_blacklist")

        mock_channel.send.assert_awaited_once()
        embeds = mock_channel.send.call_args.kwargs["embeds"]
        assert len(embeds) == 2
        assert embeds[0].image.url == "https://cdn.discordapp.com/evidence.png"
        assert embeds[1].image.url == "https://scam.xyz/banner1.png"
        assert embeds[0].url == embeds[1].url


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

    async def test_pardon_callback_forbidden(self):
        member = self._make_member()
        member.edit = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perm"))
        view = PhishingAlertView(member, "https://evil.com", "timeout", {"mod_roles": []})
        interaction = self._make_interaction()

        await view.pardon_callback(interaction)
        interaction.followup.send.assert_awaited_once_with(
            "❌ I do not have permission to edit/pardon this member.", ephemeral=True
        )

    async def test_pardon_callback_generic_exception(self):
        member = self._make_member()
        member.edit = AsyncMock(side_effect=Exception("network lag"))
        view = PhishingAlertView(member, "https://evil.com", "timeout", {"mod_roles": []})
        interaction = self._make_interaction()

        await view.pardon_callback(interaction)
        assert "Failed to pardon user" in interaction.followup.send.call_args.args[0]

    async def test_ban_callback_forbidden(self):
        member = self._make_member()
        member.ban = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perm"))
        view = PhishingAlertView(member, "https://evil.com", "timeout", {"mod_roles": []})
        interaction = self._make_interaction()

        await view.ban_callback(interaction)
        interaction.followup.send.assert_awaited_once_with(
            "❌ I do not have permission to ban this member.", ephemeral=True
        )

    async def test_ban_callback_generic_exception(self):
        member = self._make_member()
        member.ban = AsyncMock(side_effect=Exception("network lag"))
        view = PhishingAlertView(member, "https://evil.com", "timeout", {"mod_roles": []})
        interaction = self._make_interaction()

        await view.ban_callback(interaction)
        assert "Failed to ban user" in interaction.followup.send.call_args.args[0]

    async def test_allow_callback_db_exception(self, mock_db):
        member = self._make_member()
        view = PhishingAlertView(member, "https://allowed.com", "timeout", {"mod_roles": []})
        interaction = self._make_interaction()

        with patch("anti_phishing.actions.db.remove_from_blocklist", side_effect=Exception("DB fail")):
            await view.allow_callback(interaction)

        assert "Failed to allow URL" in interaction.followup.send.call_args.args[0]

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

    async def test_callbacks_preserve_all_gallery_embeds(self):
        member = self._make_member()
        member.edit = AsyncMock()

        view = PhishingAlertView(member, "https://evil.com", "timeout", {"mod_roles": []})
        interaction = self._make_interaction()
        embed1 = discord.Embed(title="Alert", url="https://discord.com")
        embed2 = discord.Embed(url="https://discord.com")
        interaction.message.embeds = [embed1, embed2]

        await view.pardon_callback(interaction)

        interaction.message.edit.assert_awaited_once()
        edited_embeds = interaction.message.edit.call_args.kwargs["embeds"]
        assert len(edited_embeds) == 2
        assert "Pardoned by" in edited_embeds[0].description
        assert edited_embeds[1].url == "https://discord.com"
