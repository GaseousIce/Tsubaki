from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

import db as db_module
from anti_phishing import domain, rate_limit
from config import AntiPhishingConfig


@pytest.fixture(autouse=True)
def clean_globals():
    domain.official.clear()
    rate_limit._tracker.clear()
    rate_limit._last_global_prune = 0.0
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


@pytest.fixture
def anti_phishing_config():
    cfg = AntiPhishingConfig()
    cfg.rate_enabled = False
    return cfg


@pytest.fixture
def official_domains():
    test_domains = {"phishing.xyz", "malware.example.com", "evil.com"}
    domain.official.update(test_domains)
    yield test_domains
    domain.official.clear()


@pytest.fixture
def simcord_bot():
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

    @bot.tree.command(name="hello", description="Say hello")
    async def hello(interaction: discord.Interaction):
        await interaction.response.send_message("hello there! :3")

    @bot.tree.command(name="ping", description="Check if the bot is online")
    async def ping(interaction: discord.Interaction):
        await interaction.response.send_message("Pong! 0 ms")

    async def setup_hook():
        await bot.tree.sync()

    bot.setup_hook = setup_hook

    return bot
