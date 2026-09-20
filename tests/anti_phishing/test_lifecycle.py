from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from anti_phishing import backfill_guild_configs, setup


class TestGuildConfigLifecycle:
    async def test_backfill_persists_defaults_for_existing_guilds(self):
        bot = MagicMock()
        bot.guilds = [MagicMock(id=10), MagicMock(id=20)]

        with patch("anti_phishing.db.get_or_create_guild_config", new_callable=AsyncMock) as ensure_config:
            await backfill_guild_configs(bot)

        assert ensure_config.await_args_list[0].args == (10,)
        assert ensure_config.await_args_list[1].args == (20,)


class TestLifecycleListenersAndTasks:
    @pytest.fixture
    def setup_context(self):
        bot = MagicMock()
        listeners = {}
        bot.add_listener = lambda func, name=None: listeners.update({name or func.__name__: func})
        bot.wait_until_ready = AsyncMock()

        captured_loops = {}

        def mock_loop(**kwargs):
            def decorator(func):
                task = MagicMock()
                task.coro = func
                task.is_running.return_value = False
                task.start = MagicMock()
                task.before_loop = lambda bfunc: bfunc
                captured_loops[func.__name__] = task
                return task

            return decorator

        with patch("discord.ext.tasks.loop", side_effect=mock_loop):
            setup(bot, {"rate_enabled": True}, enable_database_recovery=True)

        return bot, listeners, captured_loops

    async def test_on_guild_join_success(self, setup_context):
        bot, listeners, _ = setup_context
        guild = MagicMock(id=12345)

        with patch("anti_phishing.db.get_or_create_guild_config", new_callable=AsyncMock) as mock_get:
            await listeners["on_guild_join"](guild)
            mock_get.assert_awaited_once_with(12345)

    async def test_on_guild_join_db_failure(self, setup_context):
        bot, listeners, _ = setup_context
        guild = MagicMock(id=12345)

        with (
            patch("anti_phishing.db.get_or_create_guild_config", side_effect=Exception("DB fail")),
            patch("anti_phishing.logger.warning") as mock_log,
        ):
            await listeners["on_guild_join"](guild)
            mock_log.assert_called_once()
            assert "Database unavailable" in mock_log.call_args[0][0]

    async def test_prune_rate_limits_loop(self, setup_context):
        _, _, loops = setup_context
        prune_task = loops["prune_rate_limits"]

        with patch("anti_phishing.rate_limit.prune_stale_entries") as mock_prune:
            await prune_task.coro()
            mock_prune.assert_called_once()

    async def test_prune_rate_limits_exception_handled(self, setup_context):
        _, _, loops = setup_context
        prune_task = loops["prune_rate_limits"]

        with (
            patch("anti_phishing.rate_limit.prune_stale_entries", side_effect=Exception("error")),
            patch("anti_phishing.logger.warning") as mock_log,
        ):
            await prune_task.coro()
            mock_log.assert_called_once()
            assert "Failed to prune stale rate-limit entries" in mock_log.call_args[0][0]

    async def test_on_ready_success(self, setup_context):
        bot, listeners, loops = setup_context
        bot.guilds = [MagicMock(id=10)]

        with patch("anti_phishing.db.get_or_create_guild_config", new_callable=AsyncMock) as mock_cfg:
            await listeners["on_ready"]()
            mock_cfg.assert_awaited_once_with(10)

        assert loops["prune_rate_limits"].start.called
        assert loops["recover_database"].start.called

    async def test_on_ready_backfill_failure(self, setup_context):
        bot, listeners, _ = setup_context
        bot.guilds = [MagicMock(id=10)]

        with (
            patch("anti_phishing.backfill_guild_configs", side_effect=Exception("DB down")),
            patch("anti_phishing.logger.warning") as mock_log,
        ):
            await listeners["on_ready"]()
            mock_log.assert_called_once()
            assert "Database unavailable" in mock_log.call_args[0][0]

    async def test_recover_database_already_available(self, setup_context):
        _, _, loops = setup_context
        recover_task = loops["recover_database"]

        with patch("anti_phishing.db.migrate", new_callable=AsyncMock) as mock_migrate:
            # db is available by default, so recover_database should return early
            await recover_task.coro()
            mock_migrate.assert_not_called()

    async def test_recover_database_run_and_succeed(self):
        bot = MagicMock()
        listeners = {}
        bot.add_listener = lambda func, name=None: listeners.update({name or func.__name__: func})
        captured_loops = {}

        def mock_loop(**kwargs):
            def decorator(func):
                task = MagicMock()
                task.coro = func
                task.is_running.return_value = False
                task.start = MagicMock()
                task.before_loop = lambda bfunc: bfunc
                captured_loops[func.__name__] = task
                return task

            return decorator

        with patch("discord.ext.tasks.loop", side_effect=mock_loop):
            setup(bot, {"rate_enabled": True}, enable_database_recovery=True)

        # Simulate DB down during guild join to set db_available = False
        guild = MagicMock(id=123)
        with patch("anti_phishing.db.get_or_create_guild_config", side_effect=Exception("DB down")):
            await listeners["on_guild_join"](guild)

        # Now test recover_database when db_available is False
        recover_task = captured_loops["recover_database"]
        with (
            patch("anti_phishing.db.migrate", new_callable=AsyncMock) as mock_migrate,
            patch("anti_phishing.backfill_guild_configs", new_callable=AsyncMock) as mock_backfill,
        ):
            await recover_task.coro()
            mock_migrate.assert_awaited_once()
            mock_backfill.assert_awaited_once_with(bot)

    async def test_recover_database_failure_retries_later(self):
        bot = MagicMock()
        listeners = {}
        bot.add_listener = lambda func, name=None: listeners.update({name or func.__name__: func})
        captured_loops = {}

        def mock_loop(**kwargs):
            def decorator(func):
                task = MagicMock()
                task.coro = func
                task.is_running.return_value = False
                task.start = MagicMock()
                task.before_loop = lambda bfunc: bfunc
                captured_loops[func.__name__] = task
                return task

            return decorator

        with patch("discord.ext.tasks.loop", side_effect=mock_loop):
            setup(bot, {"rate_enabled": True}, enable_database_recovery=True)

        # Set db_available = False
        guild = MagicMock(id=123)
        with patch("anti_phishing.db.get_or_create_guild_config", side_effect=Exception("DB down")):
            await listeners["on_guild_join"](guild)

        recover_task = captured_loops["recover_database"]
        with (
            patch("anti_phishing.db.migrate", side_effect=Exception("still down")),
            patch("anti_phishing.logger.warning") as mock_log,
        ):
            await recover_task.coro()
            mock_log.assert_called_once()
            assert "Database recovery attempt failed" in mock_log.call_args[0][0]
