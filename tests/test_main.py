"""Tests for src/main.py lifecycle and healthcheck resilience (F30, F31, F32, F33)."""

import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import discord
import pytest

import main


class TestCommandTreeSyncResilience:
    """F30: Resilient command tree sync in setup_hook."""

    @pytest.mark.asyncio
    async def test_setup_hook_sync_success(self):
        with (
            patch("main.migrate", new_callable=AsyncMock) as mock_migrate,
            patch("main.get_groq_client"),
            patch("main.setup_commands"),
            patch("main.setup_channel_clear"),
            patch("main.setup_setup"),
            patch("main.setup_anti_phishing"),
            patch("main.fetch_official_blacklist", new_callable=AsyncMock),
            patch.object(main.bot.tree, "sync", new_callable=AsyncMock) as mock_sync,
        ):
            mock_sync.return_value = [MagicMock(), MagicMock()]
            await main.setup_hook()
            mock_migrate.assert_awaited_once()
            mock_sync.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_setup_hook_sync_http_exception_handled(self):
        """Verify setup_hook catches discord.HTTPException and does not crash."""
        with (
            patch("main.migrate", new_callable=AsyncMock),
            patch("main.get_groq_client"),
            patch("main.setup_commands"),
            patch("main.setup_channel_clear"),
            patch("main.setup_setup"),
            patch("main.setup_anti_phishing"),
            patch("main.fetch_official_blacklist", new_callable=AsyncMock),
            patch.object(main.bot.tree, "sync", new_callable=AsyncMock) as mock_sync,
            patch.object(main.logger, "error") as mock_logger_error,
        ):
            mock_response = MagicMock(status=429)
            mock_sync.side_effect = discord.HTTPException(mock_response, "Rate limited")

            # Must not raise
            await main.setup_hook()
            mock_sync.assert_awaited_once()
            mock_logger_error.assert_called_once()
            assert "Failed to sync slash commands" in mock_logger_error.call_args[0][0]


class TestGuildCommandClearingGuard:
    """F31: Guarded guild-specific command clearing in on_ready with one-time execution flag."""

    @pytest.mark.asyncio
    async def test_on_ready_clears_guild_commands_once(self):
        main._guild_commands_cleared = False
        guild1 = MagicMock(name="Guild1", id=123)
        guild2 = MagicMock(name="Guild2", id=456)

        with (
            patch.object(type(main.bot), "guilds", new_callable=PropertyMock, return_value=[guild1, guild2]),
            patch.object(main.bot.tree, "clear_commands") as mock_clear,
            patch.object(main.bot.tree, "sync", new_callable=AsyncMock) as mock_sync,
        ):
            # First on_ready call
            await main.on_ready()
            assert mock_clear.call_count == 2
            assert mock_sync.call_count == 2
            assert main._guild_commands_cleared is True

            # Second on_ready call (e.g. gateway reconnect)
            mock_clear.reset_mock()
            mock_sync.reset_mock()
            await main.on_ready()
            # Should NOT clear or sync commands again
            mock_clear.assert_not_called()
            mock_sync.assert_not_called()

        main._guild_commands_cleared = False


class TestGracefulShutdown:
    """F32: Graceful bot shutdown overriding bot.close()."""

    @pytest.mark.asyncio
    async def test_bot_close_closes_ai_service_and_db(self):
        mock_ai_service = MagicMock()
        mock_ai_service.close = AsyncMock()
        main.bot.ai_service = mock_ai_service

        with (
            patch("main.close_db", new_callable=AsyncMock) as mock_close_db,
            patch.object(main, "_original_close", new_callable=AsyncMock) as mock_orig_close,
        ):
            await main.bot.close()

            mock_ai_service.close.assert_awaited_once()
            mock_close_db.assert_awaited_once()
            mock_orig_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bot_close_resilient_to_service_errors(self):
        """Even if ai_service.close() or close_db() raises, original_close is still called."""
        mock_ai_service = MagicMock()
        mock_ai_service.close = AsyncMock(side_effect=RuntimeError("AI close error"))
        main.bot.ai_service = mock_ai_service

        with (
            patch("main.close_db", new_callable=AsyncMock, side_effect=RuntimeError("DB close error")) as mock_close_db,
            patch.object(main, "_original_close", new_callable=AsyncMock) as mock_orig_close,
            patch.object(main.logger, "warning") as mock_log_warn,
        ):
            await main.bot.close()

            mock_ai_service.close.assert_awaited_once()
            mock_close_db.assert_awaited_once()
            mock_orig_close.assert_awaited_once()
            assert mock_log_warn.call_count == 2


class TestHealthcheckServer:
    """F33: Healthcheck server resiliency and readiness checks."""

    def test_health_handler_ready_returns_200(self):
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.is_closed.return_value = False
        main.HealthHandler.bot = mock_bot

        server = HTTPServer(("127.0.0.1", 0), main.HealthHandler)
        port = server.server_port
        try:
            t = threading.Thread(target=server.handle_request)
            t.start()

            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as response:
                assert response.status == 200
                assert response.read() == b"ok"
            t.join(timeout=2)
        finally:
            server.server_close()
            main.HealthHandler.bot = None

    def test_health_handler_not_ready_returns_503(self):
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = False
        mock_bot.is_closed.return_value = False
        main.HealthHandler.bot = mock_bot

        server = HTTPServer(("127.0.0.1", 0), main.HealthHandler)
        port = server.server_port
        try:
            t = threading.Thread(target=server.handle_request)
            t.start()

            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health")
            assert exc_info.value.code == 503
            assert exc_info.value.read() == b"bot not ready"
            t.join(timeout=2)
        finally:
            server.server_close()
            main.HealthHandler.bot = None

    def test_health_handler_unknown_path_returns_404(self):
        server = HTTPServer(("127.0.0.1", 0), main.HealthHandler)
        port = server.server_port
        try:
            t = threading.Thread(target=server.handle_request)
            t.start()

            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/invalid")
            assert exc_info.value.code == 404
            t.join(timeout=2)
        finally:
            server.server_close()

    def test_start_healthcheck_server_port_binding_error(self):
        """Binding to an already bound port is caught and returns None."""
        first_server = HTTPServer(("127.0.0.1", 0), main.HealthHandler)
        busy_port = first_server.server_port
        try:
            with patch.object(main.logger, "error") as mock_log_err:
                result = main.start_healthcheck_server(port=busy_port, host="127.0.0.1")
                assert result is None
                mock_log_err.assert_called_once()
                assert "Failed to bind healthcheck server" in mock_log_err.call_args[0][0]
        finally:
            first_server.server_close()


class TestMainRunGuard:
    """Entrypoint execution guard tests."""

    def test_run_missing_token_raises_value_error(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(main, "token", None),
            pytest.raises(ValueError, match="DISCORD_TOKEN is not set"),
        ):
            main.run()
