import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import db


@pytest.fixture(autouse=True)
def reset_db():
    db._client = None
    yield


def make_mock_rows(rows_data):
    mock = MagicMock()
    mock.rows = rows_data
    return mock


class TestGetDb:
    async def test_missing_url_raises(self):
        db._client = None
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="TURSO_DATABASE_URL"):
                await db.get_db()

    async def test_missing_auth_token_raises(self):
        db._client = None
        with patch.dict(os.environ, {"TURSO_DATABASE_URL": "libsql://test.turso.io"}, clear=True):
            with pytest.raises(ValueError, match="TURSO_AUTH_TOKEN"):
                await db.get_db()


class TestMigrate:
    async def test_migrate_creates_tables(self, mock_db):
        await db.migrate()
        assert mock_db.execute.call_count >= 3

    async def test_migrate_idempotent(self, mock_db):
        await db.migrate()
        await db.migrate()
        assert mock_db.execute.call_count >= 6


class TestAntiPhishingConfig:
    async def test_update_guild_config_merges_and_persists(self, mock_db):
        from db import update_guild_config

        result = await update_guild_config(12345, enabled=False)
        assert result["enabled"] is False
        assert result["action"] == "timeout"

        call_args = mock_db.execute.call_args
        assert "INSERT INTO guild_configs" in call_args[0][0]

        import json

        parsed = json.loads(call_args[0][1][1])
        assert parsed["enabled"] is False
        assert parsed["action"] == "timeout"


class TestGuildConfig:
    async def test_get_guild_config_returns_defaults(self, mock_db):
        result = await db.get_guild_config(12345, {"key": "default"})
        assert result == {"key": "default"}

    async def test_get_guild_config_merges_stored(self, mock_db):
        stored = json.dumps({"key": "stored", "extra": "value"})
        mock_db.execute.return_value = make_mock_rows([(stored,)])
        result = await db.get_guild_config(12345, {"key": "default", "other": "default"})
        assert result["key"] == "stored"
        assert result["extra"] == "value"
        assert result["other"] == "default"

    async def test_set_guild_config(self, mock_db):
        await db.set_guild_config(12345, {"enabled": True, "action": "timeout"})
        call_args = mock_db.execute.call_args
        assert call_args[0][0].startswith("INSERT INTO guild_configs")
        parsed = json.loads(call_args[0][1][1])
        assert parsed["enabled"] is True
        assert parsed["action"] == "timeout"

    async def test_get_or_create_guild_config_persists_defaults(self, mock_db):
        result = await db.get_or_create_guild_config(12345)

        insert_call = mock_db.execute.call_args_list[1]
        assert "INSERT OR IGNORE INTO guild_configs" in insert_call.args[0]
        assert json.loads(insert_call.args[1][1]) == db.DEFAULT_GUILD_CONFIG
        assert result == db.DEFAULT_GUILD_CONFIG

    async def test_get_or_create_guild_config_preserves_stored_values(self, mock_db):
        stored = json.dumps({"enabled": False, "action": "warn"})
        mock_db.execute.return_value = make_mock_rows([(stored,)])

        result = await db.get_or_create_guild_config(12345)

        assert result["enabled"] is False
        assert result["action"] == "warn"
        assert mock_db.execute.await_count == 1


class TestDetectionLog:
    async def test_log_detection(self, mock_db):
        await db.log_detection(12345, "evil.com", "official_blacklist")
        call_args = mock_db.execute.call_args
        assert call_args[0][1] == ("12345", "evil.com", "official_blacklist")

    async def test_get_stats_empty(self, mock_db):
        stats = await db.get_stats(12345)
        assert stats["total"] == 0
        assert stats["top"] == []
        assert stats["last"] is None

    async def test_get_stats_with_data(self, mock_db):
        def side_effect(sql, params=None):
            if sql.startswith("SELECT COUNT(*)"):
                return make_mock_rows([(5,)])
            if "GROUP BY" in sql and "domain" in sql:
                return make_mock_rows([("evil.com", 3), ("phish.xyz", 2)])
            if "ORDER BY timestamp" in sql:
                return make_mock_rows([("evil.com", "official_blacklist", "2024-01-01 00:00:00")])
            return make_mock_rows([])

        mock_db.execute = AsyncMock(side_effect=side_effect)
        stats = await db.get_stats(12345)
        assert stats["total"] == 5
        assert len(stats["top"]) == 2
        assert stats["top"][0]["domain"] == "evil.com"
        assert stats["last"]["domain"] == "evil.com"


class TestCustomBlocklist:
    async def test_add_to_blocklist(self, mock_db):
        await db.add_to_blocklist("evil.com", "manual")
        call_args = mock_db.execute.call_args
        assert "INSERT OR IGNORE INTO custom_blocklist" in call_args[0][0]
        assert call_args[0][1] == ("evil.com", "manual")

    async def test_is_in_blocklist_true(self, mock_db):
        mock_db.execute.return_value = make_mock_rows([(1,)])
        result = await db.is_in_blocklist("evil.com")
        assert result is True

    async def test_is_in_blocklist_false(self, mock_db):
        result = await db.is_in_blocklist("safe.com")
        assert result is False

    async def test_get_blocklist_source(self, mock_db):
        row = MagicMock()
        row.__getitem__.return_value = "manual"
        mock_db.execute.side_effect = None
        mock_db.execute.return_value = MagicMock(rows=[row])
        result = await db.get_blocklist_source("evil.com")
        assert result == "manual"

    async def test_get_blocklist_source_none(self, mock_db):
        result = await db.get_blocklist_source("safe.com")
        assert result is None

    async def test_remove_from_blocklist_success(self, mock_db):
        mock_db.execute.return_value = make_mock_rows([])
        mock_db.execute.return_value.rows_affected = 1
        result = await db.remove_from_blocklist("evil.com")
        assert result is True

    async def test_remove_from_blocklist_not_found(self, mock_db):
        mock_db.execute.return_value = make_mock_rows([])
        mock_db.execute.return_value.rows_affected = 0
        result = await db.remove_from_blocklist("nonexistent.com")
        assert result is False


class TestConfigCache:
    async def test_cache_hits_on_subsequent_reads(self, mock_db):
        stored = json.dumps({"enabled": False, "action": "ban"})
        mock_db.execute.return_value = make_mock_rows([(stored,)])

        # First read - queries database
        result1 = await db.get_guild_config(12345)
        assert result1["enabled"] is False
        assert mock_db.execute.call_count == 1

        # Second read - hits cache (no DB query)
        result2 = await db.get_guild_config(12345)
        assert result2["enabled"] is False
        assert mock_db.execute.call_count == 1

    async def test_cache_updates_on_set(self, mock_db):
        # Populate cache
        stored = json.dumps({"enabled": True})
        mock_db.execute.return_value = make_mock_rows([(stored,)])
        await db.get_guild_config(12345)
        assert mock_db.execute.call_count == 1

        # Update config via set_guild_config
        new_cfg = {"enabled": False, "action": "kick"}
        await db.set_guild_config(12345, new_cfg)
        assert mock_db.execute.call_count == 2

        # Subsequent read should hit cache with new config immediately (no DB query)
        result = await db.get_guild_config(12345)
        assert result["enabled"] is False
        assert result["action"] == "kick"
        assert mock_db.execute.call_count == 2

    async def test_clear_config_cache(self, mock_db):
        stored = json.dumps({"enabled": False})
        mock_db.execute.return_value = make_mock_rows([(stored,)])

        await db.get_guild_config(12345)
        assert mock_db.execute.call_count == 1

        # Hit cache
        await db.get_guild_config(12345)
        assert mock_db.execute.call_count == 1

        # Clear cache
        db.clear_config_cache(12345)

        # Next read should query DB again
        await db.get_guild_config(12345)
        assert mock_db.execute.call_count == 2
