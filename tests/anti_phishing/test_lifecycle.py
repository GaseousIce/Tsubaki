from unittest.mock import AsyncMock, MagicMock, patch

from anti_phishing import backfill_guild_configs


class TestGuildConfigLifecycle:
    async def test_backfill_persists_defaults_for_existing_guilds(self):
        bot = MagicMock()
        bot.guilds = [MagicMock(id=10), MagicMock(id=20)]

        with patch("anti_phishing.db.get_or_create_guild_config", new_callable=AsyncMock) as ensure_config:
            await backfill_guild_configs(bot)

        assert ensure_config.await_args_list[0].args == (10,)
        assert ensure_config.await_args_list[1].args == (20,)
