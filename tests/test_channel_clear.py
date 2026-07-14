from unittest.mock import AsyncMock, MagicMock

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

        from unittest.mock import patch

        import channel_clear

        with patch.object(channel_clear.tasks, "loop", return_value=lambda f: mock_loop_instance):
            bot = MagicMock()
            channel_clear.setup(bot)

        mock_loop_instance.start.assert_called_once()
