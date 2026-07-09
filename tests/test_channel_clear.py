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
