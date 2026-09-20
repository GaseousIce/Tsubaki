from unittest.mock import AsyncMock, MagicMock, patch

import discord


class TestAskCommand:
    async def test_ask_no_ai_service(self, simcord_env):
        """When ai_service is None, /ask replies with a disabled message."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        # ai_service is None by default in the test bot
        result = await alice.slash(channel, "ask", question="Hello?")
        assert result.response.content == "The Groq API key is not configured yet."

    async def test_ask_success(self, simcord_env):
        """When ai_service is set and ask_tsubaki returns, /ask sends the answer."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        mock_client = MagicMock()
        simcord_env.bot.ai_service = mock_client

        with patch("commands.ask_tsubaki", new_callable=AsyncMock, return_value="Hii~ (´｡• ᵕ •｡`)"):
            result = await alice.slash(channel, "ask", question="Hello?")

        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert followup.content == "Hii~ (´｡• ᵕ •｡`)"

    async def test_ask_groq_failure(self, simcord_env):
        """When ask_tsubaki raises, /ask sends the error personality message."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        mock_client = MagicMock()
        simcord_env.bot.ai_service = mock_client

        with patch("commands.ask_tsubaki", new_callable=AsyncMock, side_effect=Exception("API down")):
            result = await alice.slash(channel, "ask", question="Hello?")

        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert "brainwaves" in followup.content

    async def test_ask_truncates_long_response(self, simcord_env):
        """Responses over 2000 chars are truncated with '...'."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        mock_client = MagicMock()
        simcord_env.bot.ai_service = mock_client

        long_answer = "a" * 2500
        with patch("commands.ask_tsubaki", new_callable=AsyncMock, return_value=long_answer):
            result = await alice.slash(channel, "ask", question="Write a novel")

        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert len(followup.content) == 2000
        assert followup.content.endswith("...")


class TestAskErrorHandling:
    async def test_cooldown_error(self):
        import commands

        bot = MagicMock()
        registered_commands = {}

        def mock_command(**kwargs):
            def decorator(func):
                cmd = MagicMock()
                cmd.callback = func

                def error_decorator(err_func):
                    cmd.on_error = err_func
                    return err_func

                cmd.error = error_decorator
                registered_commands[kwargs.get("name", func.__name__)] = cmd
                return cmd

            return decorator

        bot.tree.command = mock_command
        commands.setup(bot)
        ask_cmd = registered_commands["ask"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.send_message = AsyncMock()
        cooldown = discord.app_commands.Cooldown(1, 5.0)
        error = discord.app_commands.CommandOnCooldown(cooldown, retry_after=4.5)

        await ask_cmd.on_error(interaction, error)
        interaction.response.send_message.assert_awaited_once()
        content = interaction.response.send_message.call_args.args[0]
        assert "4.5s" in content
        assert "Don't spam me!" in content

    async def test_generic_error_response_not_done(self):
        import commands

        bot = MagicMock()
        registered_commands = {}

        def mock_command(**kwargs):
            def decorator(func):
                cmd = MagicMock()
                cmd.callback = func

                def error_decorator(err_func):
                    cmd.on_error = err_func
                    return err_func

                cmd.error = error_decorator
                registered_commands[kwargs.get("name", func.__name__)] = cmd
                return cmd

            return decorator

        bot.tree.command = mock_command
        commands.setup(bot)
        ask_cmd = registered_commands["ask"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        error = discord.app_commands.AppCommandError("Unexpected")

        await ask_cmd.on_error(interaction, error)
        interaction.response.send_message.assert_awaited_once_with("An error occurred.", ephemeral=True)

    async def test_generic_error_response_is_done(self):
        import commands

        bot = MagicMock()
        registered_commands = {}

        def mock_command(**kwargs):
            def decorator(func):
                cmd = MagicMock()
                cmd.callback = func

                def error_decorator(err_func):
                    cmd.on_error = err_func
                    return err_func

                cmd.error = error_decorator
                registered_commands[kwargs.get("name", func.__name__)] = cmd
                return cmd

            return decorator

        bot.tree.command = mock_command
        commands.setup(bot)
        ask_cmd = registered_commands["ask"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.is_done.return_value = True
        interaction.followup.send = AsyncMock()
        error = discord.app_commands.AppCommandError("Unexpected")

        await ask_cmd.on_error(interaction, error)
        interaction.followup.send.assert_awaited_once_with("An error occurred.", ephemeral=True)

    async def test_error_handler_http_exception_suppressed(self):
        import commands

        bot = MagicMock()
        registered_commands = {}

        def mock_command(**kwargs):
            def decorator(func):
                cmd = MagicMock()
                cmd.callback = func

                def error_decorator(err_func):
                    cmd.on_error = err_func
                    return err_func

                cmd.error = error_decorator
                registered_commands[kwargs.get("name", func.__name__)] = cmd
                return cmd

            return decorator

        bot.tree.command = mock_command
        commands.setup(bot)
        ask_cmd = registered_commands["ask"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "failed"))
        error = discord.app_commands.AppCommandError("Unexpected")

        await ask_cmd.on_error(interaction, error)
        interaction.response.send_message.assert_awaited_once()


class TestTestCommand:
    def test_parse_message_reference_plain_id(self):
        from commands import _parse_message_reference

        cid, mid = _parse_message_reference("123456789012345678")
        assert cid is None
        assert mid == 123456789012345678

    def test_parse_message_reference_link(self):
        from commands import _parse_message_reference

        cid, mid = _parse_message_reference("https://discord.com/channels/111111/222222/333333")
        assert cid == 222222
        assert mid == 333333

    def test_parse_message_reference_invalid(self):
        from commands import _parse_message_reference

        cid, mid = _parse_message_reference("invalid-id")
        assert cid is None
        assert mid is None

    def test_resolve_log_channel_with_alert_channel(self):
        from commands import _resolve_log_channel

        guild = MagicMock(spec=discord.Guild)
        guild.me = None
        alert_ch = MagicMock(spec=discord.TextChannel)
        guild.get_channel.return_value = alert_ch
        fallback_ch = MagicMock(spec=discord.TextChannel)

        resolved = _resolve_log_channel(guild, fallback_ch, alert_channel_ids=[999])
        assert resolved == alert_ch

    def test_resolve_log_channel_by_name(self):
        from commands import _resolve_log_channel

        guild = MagicMock(spec=discord.Guild)
        guild.me = None
        log_ch = MagicMock(spec=discord.TextChannel)
        log_ch.name = "mod-logs"
        other_ch = MagicMock(spec=discord.TextChannel)
        other_ch.name = "general"
        guild.text_channels = [other_ch, log_ch]
        guild.get_channel.return_value = None
        fallback_ch = MagicMock(spec=discord.TextChannel)

        resolved = _resolve_log_channel(guild, fallback_ch, alert_channel_ids=[])
        assert resolved == log_ch

    def test_resolve_log_channel_fallback(self):
        from commands import _resolve_log_channel

        guild = MagicMock(spec=discord.Guild)
        guild.me = None
        general_ch = MagicMock(spec=discord.TextChannel)
        general_ch.name = "general"
        guild.text_channels = [general_ch]
        guild.get_channel.return_value = None
        fallback_ch = MagicMock(spec=discord.TextChannel)

        resolved = _resolve_log_channel(guild, fallback_ch, alert_channel_ids=[])
        assert resolved == fallback_ch

    async def test_command_logs_without_action(self, simcord_env):
        """Verify /test logs message details to logs channel and DOES NOT delete message or punish user."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        logs_channel = guild.create_text_channel("bot-logs")

        mod_role = guild.create_role("Mod", permissions=discord.Permissions(manage_messages=True))
        alice = guild.add_member(simcord_env.create_user("alice"))
        mod = guild.add_member(simcord_env.create_user("moderator"), roles=[mod_role])

        # Alice sends a message
        await alice.send(channel, "Hey, check out this message!")
        target_msg = channel.last_message
        assert target_msg is not None

        # Mod runs /test on Alice's message
        result = await mod.slash(channel, "test", message_id=str(target_msg.id))

        # Check response
        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert "No action was taken" in followup.content
        assert str(target_msg.id) in followup.content

        # Message is NOT deleted!
        assert len(channel.history()) == 1
        assert channel.last_message.id == target_msg.id

        # Alice was NOT timed out or banned
        assert alice.member.timed_out_until is None

        # Logs channel received the log embed
        assert len(logs_channel.history()) == 1
        logged_msg = logs_channel.history()[0]
        assert len(logged_msg.embeds) == 1
        embed = logged_msg.embeds[0]
        assert "Test Log" in embed.title
        assert "Test Mode — Message and user untouched" in embed.description
        assert "Hey, check out this message!" in embed.fields[0].value

    async def test_command_detects_phishing_without_action(self, simcord_env, official_domains):
        """Verify /test detects phishing domain in embed without taking any action against message/user."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        logs_channel = guild.create_text_channel("logs")

        mod_role = guild.create_role("Mod", permissions=discord.Permissions(manage_messages=True))
        alice = guild.add_member(simcord_env.create_user("alice"))
        mod = guild.add_member(simcord_env.create_user("moderator"), roles=[mod_role])

        domain_name = list(official_domains)[0]

        # Alice sends message with listener disabled temporarily so it's not deleted by on_message
        with patch("anti_phishing.actions.handle_detection", new_callable=AsyncMock):
            await alice.send(channel, f"Visit https://{domain_name}/login now!")

        target_msg = channel.last_message
        assert target_msg is not None

        result = await mod.slash(channel, "test", message_id=str(target_msg.id))
        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert "No action was taken" in followup.content

        # Target message still exists (NOT deleted)
        assert channel.last_message.id == target_msg.id

        # Alice is not punished
        assert alice.member.timed_out_until is None

        # Logs channel received embed flagging the URL
        assert len(logs_channel.history()) == 1
        embed = logs_channel.history()[0].embeds[0]
        assert domain_name in embed.description
        assert "official_blacklist" in embed.description
        assert "Test Mode — Message and user untouched" in embed.description

    async def test_command_invalid_id(self, simcord_env):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        mod_role = guild.create_role("Mod", permissions=discord.Permissions(manage_messages=True))
        mod = guild.add_member(simcord_env.create_user("moderator"), roles=[mod_role])

        result = await mod.slash(channel, "test", message_id="not_a_valid_id")
        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert "Invalid message ID" in followup.content

    async def test_command_message_not_found(self, simcord_env):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        mod_role = guild.create_role("Mod", permissions=discord.Permissions(manage_messages=True))
        mod = guild.add_member(simcord_env.create_user("moderator"), roles=[mod_role])

        result = await mod.slash(channel, "test", message_id="999999999999999999")
        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert "Could not find message" in followup.content

    def test_build_test_log_embeds_multi_attachment_grid(self):
        from commands import _build_test_log_embeds

        msg = MagicMock(spec=discord.Message)
        msg.guild = MagicMock(spec=discord.Guild, name="Guild")
        msg.guild.name = "Test Guild"
        msg.guild.id = 123
        msg.channel = MagicMock(id=456)
        msg.id = 789
        msg.jump_url = "https://discord.com/channels/123/456/789"
        msg.content = "Multi image test"
        msg.embeds = []
        msg.author = MagicMock(mention="<@111>", id=111)

        att1 = MagicMock(spec=discord.Attachment, filename="one.png", url="https://cdn.discordapp.com/1.png")
        att2 = MagicMock(spec=discord.Attachment, filename="two.jpg", url="https://cdn.discordapp.com/2.jpg")
        att3 = MagicMock(spec=discord.Attachment, filename="three.gif", url="https://cdn.discordapp.com/3.gif")
        msg.attachments = [att1, att2, att3]

        tester = MagicMock(spec=discord.User)
        tester.__str__ = lambda self: "Tester#0001"

        embeds = _build_test_log_embeds(msg, None, None, tester)
        assert len(embeds) == 3
        gallery_url = embeds[0].url
        assert gallery_url == "https://discord.com/channels/123/456/789"
        expected_exts = ["png", "jpg", "gif"]
        for i, emb in enumerate(embeds):
            assert emb.url == gallery_url
            assert emb.image.url == f"https://cdn.discordapp.com/{i + 1}.{expected_exts[i]}"

    def test_build_test_log_embeds_caps_at_four(self):
        from commands import _build_test_log_embeds

        msg = MagicMock(spec=discord.Message)
        msg.guild = MagicMock(spec=discord.Guild, name="Guild")
        msg.guild.name = "Test Guild"
        msg.guild.id = 123
        msg.channel = MagicMock(id=456)
        msg.id = 789
        msg.jump_url = "https://discord.com/channels/123/456/789"
        msg.content = ""
        msg.embeds = []
        msg.author = MagicMock(mention="<@111>", id=111)
        msg.attachments = [
            MagicMock(spec=discord.Attachment, filename=f"img_{i}.png", url=f"https://cdn.discordapp.com/{i}.png")
            for i in range(7)
        ]

        tester = MagicMock(spec=discord.User)
        tester.__str__ = lambda self: "Tester#0001"

        embeds = _build_test_log_embeds(msg, None, None, tester)
        assert len(embeds) == 4
        for i, emb in enumerate(embeds):
            assert emb.url == "https://discord.com/channels/123/456/789"
            assert emb.image.url == f"https://cdn.discordapp.com/{i}.png"
