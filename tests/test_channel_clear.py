from unittest.mock import AsyncMock, MagicMock, patch

import discord
import simcord
from discord import app_commands

from channel_clear import purge_channel


class TestPurgeChannel:
    async def test_purge_success_returns_count(self):
        channel = MagicMock(spec=discord.abc.Messageable)
        channel.purge = AsyncMock(return_value=["msg1", "msg2", "msg3"])
        channel.id = 123

        result = await purge_channel(channel)
        assert result == (3, None)
        channel.purge.assert_awaited_once_with(limit=100)

    async def test_purge_forbidden_returns_forbidden(self):
        channel = MagicMock(spec=discord.abc.Messageable)
        channel.purge = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perms"))
        channel.id = 123

        result = await purge_channel(channel)
        assert result == (None, "forbidden")

    async def test_purge_http_exception_returns_api_error(self):
        channel = MagicMock(spec=discord.abc.Messageable)
        channel.purge = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "rate limited"))
        channel.id = 123

        result = await purge_channel(channel)
        assert result[0] is None
        assert "API error" in result[1]

    async def test_purge_unsupported_channel_returns_error(self):
        non_purgeable = MagicMock(spec=[])  # lacks purge method
        non_purgeable.id = 999

        result = await purge_channel(non_purgeable)
        assert result == (None, "unsupported")

    async def test_purge_with_limit_and_check(self):
        channel = MagicMock(spec=discord.abc.Messageable)
        channel.purge = AsyncMock(return_value=["msg1"])
        channel.id = 123

        def check(msg):
            return True

        result = await purge_channel(channel, limit=10, check=check)
        assert result == (1, None)
        channel.purge.assert_awaited_once_with(limit=10, check=check)


class TestDailyClearSetup:
    def test_no_channel_id_skips_loop(self, monkeypatch):
        """When CLEAR_CHANNEL_ID is unset, setup returns without starting a loop."""
        monkeypatch.delenv("CLEAR_CHANNEL_ID", raising=False)

        import channel_clear

        bot = MagicMock()
        with patch.object(channel_clear.tasks, "loop") as mock_loop:
            channel_clear.setup(bot)
            mock_loop.assert_not_called()

    def test_invalid_channel_id_skips_loop(self, monkeypatch):
        """When CLEAR_CHANNEL_ID is not a valid integer, setup returns early."""
        monkeypatch.setenv("CLEAR_CHANNEL_ID", "not-a-number")

        import channel_clear

        bot = MagicMock()
        with patch.object(channel_clear.tasks, "loop") as mock_loop, patch("channel_clear.logger.error") as mock_err:
            channel_clear.setup(bot)
            mock_loop.assert_not_called()
            mock_err.assert_called_once()
            assert "CLEAR_CHANNEL_ID is not a valid snowflake" in mock_err.call_args[0][0]

    def test_valid_channel_id_starts_loop(self, monkeypatch):
        """When CLEAR_CHANNEL_ID is a valid snowflake, the daily loop starts."""
        monkeypatch.setenv("CLEAR_CHANNEL_ID", "123456789")

        mock_loop_instance = MagicMock()

        import channel_clear

        with patch.object(channel_clear.tasks, "loop", return_value=lambda f: mock_loop_instance):
            bot = MagicMock()
            channel_clear.setup(bot)

        mock_loop_instance.start.assert_called_once()


class TestClearCommandCallback:
    async def test_clear_with_user_filter(self):
        import channel_clear

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
        channel_clear.setup(bot)
        clear_cmd = registered_commands["clear"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user = "mod#0001"
        interaction.channel = MagicMock(spec=discord.TextChannel)
        interaction.channel.purge = AsyncMock()

        target_user = MagicMock(spec=discord.Member)
        target_user.id = 111
        target_user.mention = "<@111>"

        captured_check = None

        async def fake_purge(channel, ctx_info="", limit=None, check=None):
            nonlocal captured_check
            captured_check = check
            return (2, None)

        with patch("channel_clear.purge_channel", side_effect=fake_purge):
            await clear_cmd.callback(interaction, limit=100, user=target_user)

        assert captured_check is not None
        msg_target = MagicMock()
        msg_target.author.id = 111
        msg_target.author.bot = False

        msg_other = MagicMock()
        msg_other.author.id = 222
        msg_other.author.bot = False

        assert captured_check(msg_target) is True
        assert captured_check(msg_other) is False

        interaction.followup.send.assert_awaited_once()
        content = interaction.followup.send.call_args.args[0]
        assert "from <@111>" in content

    async def test_clear_with_bots_only_filter(self):
        import channel_clear

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
        channel_clear.setup(bot)
        clear_cmd = registered_commands["clear"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user = "mod#0001"
        interaction.channel = MagicMock(spec=discord.TextChannel)
        interaction.channel.purge = AsyncMock()

        captured_check = None

        async def fake_purge(channel, ctx_info="", limit=None, check=None):
            nonlocal captured_check
            captured_check = check
            return (5, None)

        with patch("channel_clear.purge_channel", side_effect=fake_purge):
            await clear_cmd.callback(interaction, limit=100, bots_only=True)

        assert captured_check is not None
        msg_bot = MagicMock()
        msg_bot.author.id = 999
        msg_bot.author.bot = True

        msg_human = MagicMock()
        msg_human.author.id = 888
        msg_human.author.bot = False

        assert captured_check(msg_bot) is True
        assert captured_check(msg_human) is False

        interaction.followup.send.assert_awaited_once()
        content = interaction.followup.send.call_args.args[0]
        assert "from bots" in content

    async def test_clear_permission_failure(self):
        import channel_clear

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
        channel_clear.setup(bot)
        clear_cmd = registered_commands["clear"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user = "mod#0001"
        interaction.channel = MagicMock(spec=discord.TextChannel)
        interaction.channel.purge = AsyncMock()

        with patch("channel_clear.purge_channel", new_callable=AsyncMock, return_value=(None, "forbidden")):
            await clear_cmd.callback(interaction, limit=100)

        interaction.followup.send.assert_awaited_once_with(
            "❌ I don't have permission to delete messages here.", ephemeral=True
        )

    async def test_clear_api_error_feedback(self):
        import channel_clear

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
        channel_clear.setup(bot)
        clear_cmd = registered_commands["clear"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user = "mod#0001"
        interaction.channel = MagicMock(spec=discord.TextChannel)
        interaction.channel.purge = AsyncMock()

        with patch(
            "channel_clear.purge_channel", new_callable=AsyncMock, return_value=(None, "API error: Rate limited")
        ):
            await clear_cmd.callback(interaction, limit=100)

        interaction.followup.send.assert_awaited_once_with(
            "❌ Failed to clear messages: API error: Rate limited", ephemeral=True
        )

    async def test_clear_unsupported_channel_feedback(self):
        import channel_clear

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
        channel_clear.setup(bot)
        clear_cmd = registered_commands["clear"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user = "mod#0001"
        interaction.channel = MagicMock(spec=[])  # lacks purge

        await clear_cmd.callback(interaction, limit=100)

        interaction.followup.send.assert_awaited_once_with(
            "❌ This channel does not support message purging.", ephemeral=True
        )

    async def test_clear_invalid_limit_bounds(self):
        import channel_clear

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
        channel_clear.setup(bot)
        clear_cmd = registered_commands["clear"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user = "mod#0001"
        interaction.channel = MagicMock(spec=discord.TextChannel)
        interaction.channel.purge = AsyncMock()

        await clear_cmd.callback(interaction, limit=0)
        interaction.followup.send.assert_awaited_once_with(
            "❌ Limit must be between 1 and 100 messages.", ephemeral=True
        )

        interaction.followup.send.reset_mock()
        await clear_cmd.callback(interaction, limit=101)
        interaction.followup.send.assert_awaited_once_with(
            "❌ Limit must be between 1 and 100 messages.", ephemeral=True
        )


class TestClearErrorHandler:
    async def test_clear_error_missing_permissions(self):
        import channel_clear

        bot = MagicMock()
        registered_commands = {}

        def mock_command(**kwargs):
            def decorator(func):
                cmd = MagicMock()
                cmd.callback = func

                def error_dec(efunc):
                    cmd.on_error = efunc
                    return efunc

                cmd.error = error_dec
                registered_commands[kwargs.get("name", func.__name__)] = cmd
                return cmd

            return decorator

        bot.tree.command = mock_command
        channel_clear.setup(bot)
        clear_cmd = registered_commands["clear"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        error = app_commands.MissingPermissions(["manage_messages"])

        await clear_cmd.on_error(interaction, error)
        interaction.response.send_message.assert_awaited_once_with(
            "❌ You need Manage Messages permission to use /clear.", ephemeral=True
        )

    async def test_clear_error_range_error(self, monkeypatch):
        import channel_clear

        class DummyRangeError(app_commands.AppCommandError):
            pass

        monkeypatch.setattr(app_commands, "RangeError", DummyRangeError, raising=False)

        bot = MagicMock()
        registered_commands = {}

        def mock_command(**kwargs):
            def decorator(func):
                cmd = MagicMock()
                cmd.callback = func

                def error_dec(efunc):
                    cmd.on_error = efunc
                    return efunc

                cmd.error = error_dec
                registered_commands[kwargs.get("name", func.__name__)] = cmd
                return cmd

            return decorator

        bot.tree.command = mock_command
        channel_clear.setup(bot)
        clear_cmd = registered_commands["clear"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        error = DummyRangeError()

        await clear_cmd.on_error(interaction, error)
        interaction.response.send_message.assert_awaited_once_with(
            "❌ Limit must be between 1 and 100 messages.", ephemeral=True
        )

    async def test_clear_error_check_failure(self):
        import channel_clear

        bot = MagicMock()
        registered_commands = {}

        def mock_command(**kwargs):
            def decorator(func):
                cmd = MagicMock()
                cmd.callback = func

                def error_dec(efunc):
                    cmd.on_error = efunc
                    return efunc

                cmd.error = error_dec
                registered_commands[kwargs.get("name", func.__name__)] = cmd
                return cmd

            return decorator

        bot.tree.command = mock_command
        channel_clear.setup(bot)
        clear_cmd = registered_commands["clear"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        error = app_commands.CheckFailure("Failed")

        await clear_cmd.on_error(interaction, error)
        interaction.response.send_message.assert_awaited_once_with(
            "❌ You do not have permission to run this command.", ephemeral=True
        )


class TestDailyClearExecution:
    async def test_daily_clear_channel_cached(self, monkeypatch):
        monkeypatch.setenv("CLEAR_CHANNEL_ID", "123456789")
        import channel_clear

        captured_task = None
        captured_before = None

        def fake_loop(**kwargs):
            def decorator(func):
                mock_task = MagicMock()
                mock_task.coro = func

                def before_loop(bfunc):
                    nonlocal captured_before
                    captured_before = bfunc
                    return bfunc

                mock_task.before_loop = before_loop
                mock_task.error = lambda f: f
                nonlocal captured_task
                captured_task = mock_task
                return mock_task

            return decorator

        bot = MagicMock()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.purge = AsyncMock()
        bot.get_channel.return_value = mock_channel
        bot.wait_until_ready = AsyncMock()

        with patch.object(channel_clear.tasks, "loop", side_effect=fake_loop):
            with patch("channel_clear.purge_channel", new_callable=AsyncMock, return_value=(5, None)) as mock_purge:
                channel_clear.setup(bot)
                await captured_task.coro()
                await captured_before()

        bot.get_channel.assert_called_once_with(123456789)
        mock_purge.assert_awaited_once_with(mock_channel, "(daily)", limit=100)
        bot.wait_until_ready.assert_awaited_once()

    async def test_daily_clear_channel_fetched(self, monkeypatch):
        monkeypatch.setenv("CLEAR_CHANNEL_ID", "123456789")
        import channel_clear

        captured_task = None

        def fake_loop(**kwargs):
            def decorator(func):
                mock_task = MagicMock()
                mock_task.coro = func
                mock_task.before_loop = lambda f: f
                mock_task.error = lambda f: f
                nonlocal captured_task
                captured_task = mock_task
                return mock_task

            return decorator

        bot = MagicMock()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.purge = AsyncMock()
        bot.get_channel.return_value = None
        bot.fetch_channel = AsyncMock(return_value=mock_channel)

        with patch.object(channel_clear.tasks, "loop", side_effect=fake_loop):
            with patch("channel_clear.purge_channel", new_callable=AsyncMock, return_value=(5, None)) as mock_purge:
                channel_clear.setup(bot)
                await captured_task.coro()

        bot.fetch_channel.assert_awaited_once_with(123456789)
        mock_purge.assert_awaited_once_with(mock_channel, "(daily)", limit=100)

    async def test_daily_clear_channel_not_found(self, monkeypatch):
        monkeypatch.setenv("CLEAR_CHANNEL_ID", "123456789")
        import channel_clear

        captured_task = None

        def fake_loop(**kwargs):
            def decorator(func):
                mock_task = MagicMock()
                mock_task.coro = func
                mock_task.before_loop = lambda f: f
                mock_task.error = lambda f: f
                nonlocal captured_task
                captured_task = mock_task
                return mock_task

            return decorator

        bot = MagicMock()
        bot.get_channel.return_value = None
        bot.fetch_channel = AsyncMock(return_value=None)

        with patch.object(channel_clear.tasks, "loop", side_effect=fake_loop):
            with patch("channel_clear.purge_channel", new_callable=AsyncMock) as mock_purge:
                channel_clear.setup(bot)
                await captured_task.coro()

        mock_purge.assert_not_called()

    async def test_daily_clear_channel_unsupported_type(self, monkeypatch):
        monkeypatch.setenv("CLEAR_CHANNEL_ID", "123456789")
        import channel_clear

        captured_task = None

        def fake_loop(**kwargs):
            def decorator(func):
                mock_task = MagicMock()
                mock_task.coro = func
                mock_task.before_loop = lambda f: f
                mock_task.error = lambda f: f
                nonlocal captured_task
                captured_task = mock_task
                return mock_task

            return decorator

        bot = MagicMock()
        non_text_channel = MagicMock(spec=[])  # lacks purge method
        bot.get_channel.return_value = non_text_channel

        with patch.object(channel_clear.tasks, "loop", side_effect=fake_loop):
            with (
                patch("channel_clear.purge_channel", new_callable=AsyncMock) as mock_purge,
                patch("channel_clear.logger.error") as mock_log,
            ):
                channel_clear.setup(bot)
                await captured_task.coro()
                mock_purge.assert_not_called()
                assert any("does not support purge" in str(arg) for call in mock_log.call_args_list for arg in call[0])

    async def test_daily_clear_exception_handled(self, monkeypatch):
        monkeypatch.setenv("CLEAR_CHANNEL_ID", "123456789")
        import channel_clear

        captured_task = None

        def fake_loop(**kwargs):
            def decorator(func):
                mock_task = MagicMock()
                mock_task.coro = func
                mock_task.before_loop = lambda f: f
                mock_task.error = lambda f: f
                nonlocal captured_task
                captured_task = mock_task
                return mock_task

            return decorator

        bot = MagicMock()
        bot.get_channel.side_effect = Exception("Discord API explosion")

        with (
            patch.object(channel_clear.tasks, "loop", side_effect=fake_loop),
            patch("channel_clear.logger.exception") as mock_log,
        ):
            channel_clear.setup(bot)
            await captured_task.coro()
            mock_log.assert_called_once()
            assert "Failed to run daily channel clear" in mock_log.call_args[0][0]

    async def test_daily_clear_error_listener(self, monkeypatch):
        monkeypatch.setenv("CLEAR_CHANNEL_ID", "123456789")
        import channel_clear

        captured_error_handler = None

        def fake_loop(**kwargs):
            def decorator(func):
                mock_task = MagicMock()
                mock_task.coro = func
                mock_task.before_loop = lambda f: f

                def error_dec(efunc):
                    nonlocal captured_error_handler
                    captured_error_handler = efunc
                    return efunc

                mock_task.error = error_dec
                return mock_task

            return decorator

        bot = MagicMock()
        with (
            patch.object(channel_clear.tasks, "loop", side_effect=fake_loop),
            patch("channel_clear.logger.exception") as mock_log,
        ):
            channel_clear.setup(bot)
            assert captured_error_handler is not None
            await captured_error_handler(RuntimeError("Task loop crashed"))
            mock_log.assert_called_once()
            assert "Unhandled exception in daily_clear task loop" in mock_log.call_args[0][0]


class TestClearSimCordIntegration:
    async def test_simcord_clear_with_permission(self, simcord_env):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        mod_role = guild.create_role("Mod", permissions=discord.Permissions(manage_messages=True))
        mod = guild.add_member(simcord_env.create_user("mod"), roles=[mod_role])
        user = guild.add_member(simcord_env.create_user("user"))

        for i in range(5):
            await user.send(channel, f"Message {i}")

        assert len(channel.history()) == 5

        result = await mod.slash(channel, "clear", limit=3)
        assert result.followups
        assert "Successfully cleared **3** messages" in result.followups[0].content
        assert len(channel.history()) == 2

    async def test_simcord_clear_unprivileged_rejected(self, simcord_env):
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        user = guild.add_member(simcord_env.create_user("user"))

        await user.send(channel, "Cannot delete me")

        result = await user.slash(channel, "clear")
        assert result.response is not None
        assert "Manage Messages permission" in result.response.content
        assert len(channel.history()) == 1
        simcord.asserts.assert_error(simcord_env, app_commands.errors.MissingPermissions)
