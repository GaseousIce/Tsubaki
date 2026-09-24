from unittest.mock import AsyncMock, MagicMock, patch

import discord
import simcord


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

    async def test_ask_mention_injection_suppression(self):
        """Verify /ask passes allowed_mentions=discord.AllowedMentions.none() to suppress pings."""
        import commands

        bot = MagicMock()
        registered_commands = {}

        def mock_command(**kwargs):
            def decorator(func):
                cmd = MagicMock()
                cmd.callback = func
                cmd.error = lambda f: f
                registered_commands[kwargs.get("name", func.__name__)] = cmd
                return cmd

            return decorator

        bot.tree.command = mock_command
        bot.ai_service = MagicMock()
        commands.setup(bot)
        ask_cmd = registered_commands["ask"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock()
        cm.__aexit__ = AsyncMock()
        interaction.channel.typing.return_value = cm

        with patch("commands.ask_tsubaki", new_callable=AsyncMock, return_value="Check @everyone and <@&12345>"):
            await ask_cmd.callback(interaction, question="ping everyone")

        interaction.followup.send.assert_awaited_once()
        _, kwargs = interaction.followup.send.call_args
        assert "allowed_mentions" in kwargs
        am = kwargs["allowed_mentions"]
        assert isinstance(am, discord.AllowedMentions)
        assert am.everyone is False
        assert am.roles is False
        assert am.users is False


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

    # --- F39: Runtime permission checks & error handling ---

    async def test_command_requires_manage_messages(self, simcord_env):
        """Unprivileged member running /test is rejected with MissingPermissions."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        result = await alice.slash(channel, "test", message_id="123456789")
        assert result.response is not None
        assert "do not have permission" in result.response.content
        simcord.asserts.assert_error(simcord_env, discord.app_commands.errors.MissingPermissions)

    async def test_command_allowed_for_admin(self, simcord_env):
        """Admin member running /test succeeds and proceeds to message resolution."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
        admin = guild.add_member(simcord_env.create_user("admin"), roles=[admin_role])

        result = await admin.slash(channel, "test", message_id="123456789")
        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert "Could not find message" in followup.content

    async def test_test_cmd_error_missing_permissions_not_done(self):
        """Unit test for test_cmd_error when response is not done."""
        import commands

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
        commands.setup(bot)
        test_cmd = registered["test"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        error = discord.app_commands.MissingPermissions(["manage_messages"])

        await test_cmd.on_error(interaction, error)
        interaction.response.send_message.assert_awaited_once_with(
            "❌ You do not have permission to run this command.", ephemeral=True
        )

    async def test_test_cmd_error_missing_permissions_done(self):
        """Unit test for test_cmd_error when response is done."""
        import commands

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
        commands.setup(bot)
        test_cmd = registered["test"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.is_done.return_value = True
        interaction.followup.send = AsyncMock()
        error = discord.app_commands.MissingPermissions(["manage_messages"])

        await test_cmd.on_error(interaction, error)
        interaction.followup.send.assert_awaited_once_with(
            "❌ You do not have permission to run this command.", ephemeral=True
        )

    # --- F40: Cross-channel IDOR protection ---

    def test_can_access_channel_perms(self):
        """Unit test for _can_access_channel permission evaluation."""
        from commands import _can_access_channel

        channel = MagicMock(spec=discord.TextChannel)
        member = MagicMock(spec=discord.Member)

        perms = MagicMock()
        perms.view_channel = True
        perms.read_message_history = True
        channel.permissions_for.return_value = perms

        assert _can_access_channel(channel, member) is True

        perms.view_channel = False
        assert _can_access_channel(channel, member) is False

        perms.view_channel = True
        perms.read_message_history = False
        assert _can_access_channel(channel, member) is False

        assert _can_access_channel(channel, None) is True

    async def test_cross_channel_idor_prevented_with_link(self, simcord_env):
        """Mod cannot inspect message in secret channel via jump link."""
        guild = simcord_env.create_guild()
        general = guild.create_text_channel("general")
        logs_channel = guild.create_text_channel("bot-logs")
        everyone = guild.roles["@everyone"]
        mod_role = guild.create_role("Mod", permissions=discord.Permissions(manage_messages=True))

        secret_ch = guild.create_text_channel(
            "secret-vault",
            overwrites={
                everyone: discord.PermissionOverwrite(view_channel=False),
                mod_role: discord.PermissionOverwrite(view_channel=False),
            },
        )
        admin = guild.add_member(
            simcord_env.create_user("admin"),
            roles=[guild.create_role("Admin", permissions=discord.Permissions(administrator=True))],
        )
        mod = guild.add_member(simcord_env.create_user("mod"), roles=[mod_role])

        await admin.send(secret_ch, "Confidential admin password: hunter2")
        secret_msg = secret_ch.last_message
        assert secret_msg is not None

        jump_link = f"https://discord.com/channels/{guild.id}/{secret_ch.id}/{secret_msg.id}"
        result = await mod.slash(general, "test", message_id=jump_link)

        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert "Could not find message" in followup.content
        assert len(logs_channel.history()) == 0

    async def test_cross_channel_idor_prevented_plain_id(self, simcord_env):
        """Mod cannot inspect message in secret channel by searching plain message ID."""
        guild = simcord_env.create_guild()
        general = guild.create_text_channel("general")
        logs_channel = guild.create_text_channel("bot-logs")
        everyone = guild.roles["@everyone"]
        mod_role = guild.create_role("Mod", permissions=discord.Permissions(manage_messages=True))

        secret_ch = guild.create_text_channel(
            "secret-vault",
            overwrites={
                everyone: discord.PermissionOverwrite(view_channel=False),
                mod_role: discord.PermissionOverwrite(view_channel=False),
            },
        )
        admin = guild.add_member(
            simcord_env.create_user("admin"),
            roles=[guild.create_role("Admin", permissions=discord.Permissions(administrator=True))],
        )
        mod = guild.add_member(simcord_env.create_user("mod"), roles=[mod_role])

        await admin.send(secret_ch, "Confidential admin password: hunter2")
        secret_msg = secret_ch.last_message
        assert secret_msg is not None

        result = await mod.slash(general, "test", message_id=str(secret_msg.id))

        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert "Could not find message" in followup.content
        assert len(logs_channel.history()) == 0

    async def test_cross_channel_authorized_access(self, simcord_env):
        """Mod can inspect message across channels when they have view & read permissions."""
        guild = simcord_env.create_guild()
        general = guild.create_text_channel("general")
        public_other = guild.create_text_channel("public-chat")
        logs_channel = guild.create_text_channel("bot-logs")
        mod_role = guild.create_role("Mod", permissions=discord.Permissions(manage_messages=True))
        alice = guild.add_member(simcord_env.create_user("alice"))
        mod = guild.add_member(simcord_env.create_user("mod"), roles=[mod_role])

        await alice.send(public_other, "Public announcement to inspect")
        target_msg = public_other.last_message

        result = await mod.slash(general, "test", message_id=str(target_msg.id))
        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert "No action was taken" in followup.content
        assert len(logs_channel.history()) == 1

    # --- F41: Strict log channel resolution ---

    def test_resolve_log_channel_ignores_substring_false_positives(self):
        """_resolve_log_channel does not match #changelog, #blog, #catalog, etc."""
        from commands import _resolve_log_channel

        guild = MagicMock(spec=discord.Guild)
        guild.me = None
        false_positive_names = ["changelog", "blog", "catalog", "prologue", "backlog", "login", "logo"]
        guild.text_channels = []
        for name in false_positive_names:
            ch = MagicMock(spec=discord.TextChannel)
            ch.name = name
            guild.text_channels.append(ch)

        fallback_ch = MagicMock(spec=discord.TextChannel)
        resolved = _resolve_log_channel(guild, fallback_ch, alert_channel_ids=[])
        assert resolved == fallback_ch

    def test_resolve_log_channel_matches_valid_tokens(self):
        """_resolve_log_channel correctly matches log and alert channel variations."""
        from commands import _resolve_log_channel

        guild = MagicMock(spec=discord.Guild)
        guild.me = None
        valid_names = ["audit-log", "server-logs", "bot_log", "modlogs", "alerts", "mod-alert"]
        for name in valid_names:
            ch = MagicMock(spec=discord.TextChannel)
            ch.name = name
            guild.text_channels = [ch]
            fallback_ch = MagicMock(spec=discord.TextChannel)
            resolved = _resolve_log_channel(guild, fallback_ch, alert_channel_ids=[])
            assert resolved == ch, f"Failed to match valid log channel name: {name}"

    # --- F44: Redundant typing removal in /ask ---

    async def test_ask_channel_none_resilience(self):
        """/ask completes even when interaction.channel is None."""
        import commands

        bot = MagicMock()
        registered = {}

        def mock_command(**kwargs):
            def decorator(func):
                cmd = MagicMock()
                cmd.callback = func
                cmd.error = lambda f: f
                registered[kwargs.get("name", func.__name__)] = cmd
                return cmd

            return decorator

        bot.tree.command = mock_command
        bot.ai_service = MagicMock()
        commands.setup(bot)
        ask_cmd = registered["ask"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.channel = None
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        with patch("commands.ask_tsubaki", new_callable=AsyncMock, return_value="Hello, world!"):
            await ask_cmd.callback(interaction, question="hi")

        interaction.followup.send.assert_awaited_once()
        assert interaction.followup.send.call_args.args[0] == "Hello, world!"
