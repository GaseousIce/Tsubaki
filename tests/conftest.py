from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import simcord
from discord.ext import commands

import db as db_module
from anti_phishing import domain, rate_limit


@pytest.fixture(autouse=True)
def clean_globals():
    domain.official.clear()
    rate_limit._tracker.clear()
    db_module._client = None
    yield


@pytest.fixture(autouse=True)
def mock_db():
    """Prevent real network by mocking libsql create_client only.
    All db module functions run their real implementation.
    """
    mock_client = MagicMock()
    mock_client.execute = AsyncMock(return_value=MagicMock(rows=[]))

    with (
        patch.object(db_module, "create_client", return_value=mock_client),
        patch.dict(
            "os.environ",
            {
                "TURSO_DATABASE_URL": "libsql://test.turso.io",
                "TURSO_AUTH_TOKEN": "test-token",
            },
            clear=False,
        ),
    ):
        yield mock_client


@pytest.fixture
def mock_db_with_blocklist(mock_db):
    """Configure the mock client so get_blocklist_source returns a row."""
    row = MagicMock()
    row.__getitem__.return_value = "test-source"
    mock_db.execute.side_effect = None
    mock_db.execute.return_value = MagicMock(rows=[row])
    yield mock_db


def _build_bot(config: dict) -> commands.Bot:
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)
    bot.ai_service = None

    from commands import setup as setup_commands

    setup_commands(bot)

    from anti_phishing import setup as setup_anti_phishing

    setup_anti_phishing(bot, config)

    from channel_clear import setup as setup_channel_clear

    setup_channel_clear(bot)

    from setup import setup as setup_setup

    setup_setup(bot)

    async def setup_hook():
        await bot.tree.sync()

    bot.setup_hook = setup_hook

    return bot


@pytest.fixture
def anti_phishing_config():
    return {"rate_enabled": False, "rate_threshold": 3, "rate_window": 10, "fetch_retries": 3}


@pytest.fixture
def anti_phishing_config_rate():
    return {"rate_enabled": True, "rate_threshold": 3, "rate_window": 10, "fetch_retries": 3}


@pytest.fixture
def official_domains():
    test_domains = {"phishing.xyz", "malware.example.com", "evil.com"}
    domain.official.update(test_domains)
    yield test_domains
    domain.official.clear()


@pytest.fixture
async def simcord_bot(anti_phishing_config):
    return _build_bot(anti_phishing_config)


@pytest.fixture
async def simcord_bot_rate(anti_phishing_config_rate):
    return _build_bot(anti_phishing_config_rate)


@pytest.fixture
async def simcord_env_rate(simcord_bot_rate):
    async with simcord.run(simcord_bot_rate) as env:
        yield env
