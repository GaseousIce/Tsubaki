import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import db


@pytest.fixture(autouse=True)
def reset_db():
    db._client = None
    db._client_lock = None
    db.clear_config_cache()
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

    async def test_get_db_recreates_closed_client(self, mock_db):
        client1 = await db.get_db()
        assert client1 is mock_db
        mock_db.closed = True

        fresh_client = MagicMock()
        fresh_client.closed = False
        fresh_client.close = AsyncMock()

        with patch.object(db, "create_client", return_value=fresh_client):
            client2 = await db.get_db()
            assert client2 is fresh_client
            assert client2 is not client1

    async def test_get_db_concurrency_lock(self):
        db._client = None
        created_clients = []

        def fake_create(url, auth_token):
            c = MagicMock()
            c.closed = False
            created_clients.append(c)
            return c

        with (
            patch.object(db, "create_client", side_effect=fake_create),
            patch.dict(os.environ, {"TURSO_DATABASE_URL": "libsql://x", "TURSO_AUTH_TOKEN": "y"}),
        ):
            clients = await asyncio.gather(*(db.get_db() for _ in range(10)))
            assert len(created_clients) == 1
            assert all(c is created_clients[0] for c in clients)

    async def test_close_db(self, mock_db):
        await db.get_db()
        assert db._client is not None
        await db.close_db()
        mock_db.close.assert_awaited_once()
        assert db._client is None

    async def test_close_db_idempotent_when_none(self):
        db._client = None
        await db.close_db()
        assert db._client is None


class TestMigrate:
    async def test_migrate_creates_tables(self, mock_db):
        await db.migrate()
        executed_sqls = [c[0][0] for c in mock_db.execute.call_args_list]
        assert any("CREATE TABLE IF NOT EXISTS guild_configs" in sql for sql in executed_sqls)
        assert any("CREATE TABLE IF NOT EXISTS detection_log" in sql for sql in executed_sqls)
        assert any(
            "CREATE TABLE IF NOT EXISTS custom_blocklist" in sql and "COLLATE NOCASE" in sql for sql in executed_sqls
        )
        assert any("CREATE TABLE IF NOT EXISTS typosquat_patterns" in sql for sql in executed_sqls)
        assert any("CREATE INDEX IF NOT EXISTS idx_detection_log_guild_timestamp" in sql for sql in executed_sqls)
        assert any("CREATE INDEX IF NOT EXISTS idx_detection_log_guild_domain" in sql for sql in executed_sqls)
        assert any("PRAGMA table_info(detection_log)" in sql for sql in executed_sqls)

    async def test_migrate_idempotent(self, mock_db):
        await db.migrate()
        await db.migrate()
        assert mock_db.execute.call_count >= 12

    async def test_migrate_adds_missing_columns(self, mock_db):
        # Simulate an existing table with only the old columns
        mock_db.execute.side_effect = [
            MagicMock(),  # CREATE TABLE guild_configs
            MagicMock(),  # CREATE TABLE detection_log
            MagicMock(),  # CREATE TABLE custom_blocklist
            MagicMock(),  # CREATE TABLE typosquat_patterns (F24)
            MagicMock(),  # CREATE INDEX idx_detection_log_guild_timestamp
            MagicMock(),  # CREATE INDEX idx_detection_log_guild_domain
            make_mock_rows([(0, "id"), (1, "guild_id"), (2, "domain"), (3, "reason"), (4, "timestamp")]),  # PRAGMA
            MagicMock(),  # ALTER TABLE content
            MagicMock(),  # ALTER TABLE attachments
        ]
        await db.migrate()
        executed_sqls = [c[0][0] for c in mock_db.execute.call_args_list]
        assert any("ADD COLUMN content" in sql for sql in executed_sqls)
        assert any("ADD COLUMN attachments" in sql for sql in executed_sqls)


class TestAntiPhishingConfig:
    async def test_update_guild_config_merges_and_persists(self, mock_db):
        from db import update_guild_config

        result = await update_guild_config(12345, enabled=False)
        assert result["enabled"] is False
        assert result["action"] == "timeout"

        call_args = mock_db.execute.call_args
        assert "INSERT INTO guild_configs" in call_args[0][0]

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

    async def test_default_guild_config_pollution_prevention(self, mock_db):
        cfg1 = await db.get_guild_config(11111)
        cfg1["alert_channels"].append(99999)
        cfg1["mod_roles"].append(88888)

        cfg2 = await db.get_guild_config(22222)
        assert cfg2["alert_channels"] == []
        assert cfg2["mod_roles"] == []
        assert db.DEFAULT_GUILD_CONFIG["alert_channels"] == []
        assert db.DEFAULT_GUILD_CONFIG["mod_roles"] == []

    async def test_cache_mutation_isolation(self, mock_db):
        await db.set_guild_config(12345, {"alert_channels": [100]})
        cfg1 = await db.get_guild_config(12345)
        cfg1["alert_channels"].append(200)

        cfg2 = await db.get_guild_config(12345)
        assert cfg2["alert_channels"] == [100]

    async def test_get_guild_config_corrupted_json_fallback(self, mock_db):
        mock_db.execute.return_value = make_mock_rows([("{broken_json: 123",)])
        cfg = await db.get_guild_config(12345)
        assert cfg == db.DEFAULT_GUILD_CONFIG

    async def test_get_guild_config_non_dict_json_fallback(self, mock_db):
        mock_db.execute.return_value = make_mock_rows([("[1, 2, 3]",)])
        cfg = await db.get_guild_config(12345)
        assert cfg == db.DEFAULT_GUILD_CONFIG

    async def test_get_or_create_guild_config_corrupted_json_fallback(self, mock_db):
        mock_db.execute.return_value = make_mock_rows([("not json at all",)])
        cfg = await db.get_or_create_guild_config(12345)
        assert cfg == db.DEFAULT_GUILD_CONFIG

    async def test_update_guild_config_atomic_lock(self, mock_db):
        stored = json.dumps({"enabled": True, "action": "timeout"})
        mock_db.execute.return_value = make_mock_rows([(stored,)])

        res1, res2 = await asyncio.gather(
            db.update_guild_config(12345, action="ban"),
            db.update_guild_config(12345, enabled=False),
        )
        assert res1 is not None
        assert res2 is not None


class TestDetectionLog:
    async def test_log_detection(self, mock_db):
        await db.log_detection(12345, "evil.com", "official_blacklist")
        call_args = mock_db.execute.call_args
        assert call_args[0][1] == ("12345", "evil.com", "official_blacklist", None, None)

    async def test_log_detection_with_content_and_attachments(self, mock_db):
        await db.log_detection(
            12345,
            "evil.com",
            "rate_limit",
            content="Check this image!",
            attachments=["https://cdn.discordapp.com/1.png"],
        )
        call_args = mock_db.execute.call_args
        assert call_args[0][1] == (
            "12345",
            "evil.com",
            "rate_limit",
            "Check this image!",
            '["https://cdn.discordapp.com/1.png"]',
        )

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
        # Positional tuple row
        mock_db.execute.side_effect = None
        mock_db.execute.return_value = make_mock_rows([("manual",)])
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

    async def test_custom_blocklist_case_insensitivity(self, mock_db):
        await db.add_to_blocklist("  EVIL.COM  ", "manual")
        call_args = mock_db.execute.call_args
        assert call_args[0][1] == ("evil.com", "manual")

        await db.is_in_blocklist("EvIL.cOm")
        call_args = mock_db.execute.call_args
        assert call_args[0][1] == ("evil.com",)

        mock_db.execute.return_value = make_mock_rows([("manual",)])
        res = await db.get_blocklist_source("Evil.Com")
        assert res == "manual"
        call_args = mock_db.execute.call_args
        assert call_args[0][1] == ("evil.com",)

        await db.remove_from_blocklist("  EVIL.COM  ")
        call_args = mock_db.execute.call_args
        assert call_args[0][1] == ("evil.com",)


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

    async def test_clear_config_cache_all(self, mock_db):
        stored = json.dumps({"enabled": True})
        mock_db.execute.return_value = make_mock_rows([(stored,)])

        await db.get_guild_config(12345)
        assert mock_db.execute.call_count == 1

        db.clear_config_cache(None)

        await db.get_guild_config(12345)
        assert mock_db.execute.call_count == 2

    async def test_cache_lru_eviction(self, mock_db):
        with patch.object(db, "MAX_CONFIG_CACHE_SIZE", 3):
            await db.set_guild_config(1, {"val": 1})
            await db.set_guild_config(2, {"val": 2})
            await db.set_guild_config(3, {"val": 3})

            # Access 1 so 2 becomes the oldest
            await db.get_guild_config(1)

            # Insert 4, which should evict 2
            await db.set_guild_config(4, {"val": 4})

            assert 2 not in db._config_cache
            assert 1 in db._config_cache
            assert 3 in db._config_cache
            assert 4 in db._config_cache
