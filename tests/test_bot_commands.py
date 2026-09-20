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
