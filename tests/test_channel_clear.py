from unittest.mock import AsyncMock, MagicMock, patch

import discord

from channel_clear import purge_channel


class TestPurgeChannel:
    async def test_purge_success_returns_count(self):
        channel = MagicMock(spec=discord.abc.Messageable)
        channel.purge = AsyncMock(return_value=["msg1", "msg2", "msg3"])
        channel.id = 123

        result = await purge_channel(channel)
        assert result == 3
        channel.purge.assert_awaited_once()

    async def test_purge_forbidden_returns_none(self):
        channel = MagicMock(spec=discord.abc.Messageable)
        channel.purge = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perms"))
        channel.id = 123

        result = await purge_channel(channel)
        assert result is None

    async def test_purge_http_exception_returns_none(self):
        channel = MagicMock(spec=discord.abc.Messageable)
        channel.purge = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "rate limited"))
        channel.id = 123

        result = await purge_channel(channel)
        assert result is None

    async def test_purge_with_limit_and_check(self):
        channel = MagicMock(spec=discord.abc.Messageable)
        channel.purge = AsyncMock(return_value=["msg1"])
        channel.id = 123

        def check(msg):
            return True

        result = await purge_channel(channel, limit=10, check=check)
        assert result == 1
        channel.purge.assert_awaited_once_with(limit=10, check=check)


class TestDailyClearSetup:
    def test_no_channel_id_skips_loop(self, monkeypatch):
        """When CLEAR_CHANNEL_ID is unset, setup returns without starting a loop."""
        monkeypatch.delenv("CLEAR_CHANNEL_ID", raising=False)

        import channel_clear

        bot = MagicMock()
        # Should not raise — just logs a warning and returns
        channel_clear.setup(bot)

    def test_invalid_channel_id_skips_loop(self, monkeypatch):
        """When CLEAR_CHANNEL_ID is not a valid integer, setup returns early."""
        monkeypatch.setenv("CLEAR_CHANNEL_ID", "not-a-number")

        import channel_clear

        bot = MagicMock()
        # Should not raise — logs an error and returns
        channel_clear.setup(bot)

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
                registered_commands[kwargs.get("name", func.__name__)] = func
                return func

            return decorator

        bot.tree.command = mock_command
        channel_clear.setup(bot)
        clear_func = registered_commands["clear"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user = "mod#0001"

        target_user = MagicMock(spec=discord.Member)
        target_user.id = 111
        target_user.mention = "<@111>"

        captured_check = None

        async def fake_purge(channel, ctx_info="", limit=None, check=None):
            nonlocal captured_check
            captured_check = check
            return 2

        with patch("channel_clear.purge_channel", side_effect=fake_purge):
            await clear_func(interaction, user=target_user)

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
                registered_commands[kwargs.get("name", func.__name__)] = func
                return func

            return decorator

        bot.tree.command = mock_command
        channel_clear.setup(bot)
        clear_func = registered_commands["clear"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user = "mod#0001"

        captured_check = None

        async def fake_purge(channel, ctx_info="", limit=None, check=None):
            nonlocal captured_check
            captured_check = check
            return 5

        with patch("channel_clear.purge_channel", side_effect=fake_purge):
            await clear_func(interaction, bots_only=True)

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
                registered_commands[kwargs.get("name", func.__name__)] = func
                return func

            return decorator

        bot.tree.command = mock_command
        channel_clear.setup(bot)
        clear_func = registered_commands["clear"]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user = "mod#0001"

        with patch("channel_clear.purge_channel", new_callable=AsyncMock, return_value=None):
            await clear_func(interaction)

        interaction.followup.send.assert_awaited_once_with(
            "❌ I don't have permission to delete messages here.", ephemeral=True
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
                nonlocal captured_task
                captured_task = mock_task
                return mock_task

            return decorator

        bot = MagicMock()
        mock_channel = MagicMock()
        bot.get_channel.return_value = mock_channel
        bot.wait_until_ready = AsyncMock()

        with patch.object(channel_clear.tasks, "loop", side_effect=fake_loop):
            with patch("channel_clear.purge_channel", new_callable=AsyncMock) as mock_purge:
                channel_clear.setup(bot)
                await captured_task.coro()
                await captured_before()

        bot.get_channel.assert_called_once_with(123456789)
        mock_purge.assert_awaited_once_with(mock_channel, "(daily)")
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
                nonlocal captured_task
                captured_task = mock_task
                return mock_task

            return decorator

        bot = MagicMock()
        mock_channel = MagicMock()
        bot.get_channel.return_value = None
        bot.fetch_channel = AsyncMock(return_value=mock_channel)

        with patch.object(channel_clear.tasks, "loop", side_effect=fake_loop):
            with patch("channel_clear.purge_channel", new_callable=AsyncMock) as mock_purge:
                channel_clear.setup(bot)
                await captured_task.coro()

        bot.fetch_channel.assert_awaited_once_with(123456789)
        mock_purge.assert_awaited_once_with(mock_channel, "(daily)")

    async def test_daily_clear_channel_not_found(self, monkeypatch):
        monkeypatch.setenv("CLEAR_CHANNEL_ID", "123456789")
        import channel_clear

        captured_task = None

        def fake_loop(**kwargs):
            def decorator(func):
                mock_task = MagicMock()
                mock_task.coro = func
                mock_task.before_loop = lambda f: f
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

    async def test_daily_clear_exception_handled(self, monkeypatch):
        monkeypatch.setenv("CLEAR_CHANNEL_ID", "123456789")
        import channel_clear

        captured_task = None

        def fake_loop(**kwargs):
            def decorator(func):
                mock_task = MagicMock()
                mock_task.coro = func
                mock_task.before_loop = lambda f: f
                nonlocal captured_task
                captured_task = mock_task
                return mock_task

            return decorator

        bot = MagicMock()
        bot.get_channel.side_effect = Exception("Discord API explosion")

        with patch.object(channel_clear.tasks, "loop", side_effect=fake_loop):
            channel_clear.setup(bot)
            # Should not raise
            await captured_task.coro()
