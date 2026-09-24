from anti_phishing import rate_limit


class TestRateLimitCheck:
    def test_not_triggered_below_threshold(self):
        assert rate_limit.rate_limit_check(1, 100, "hello", 10, 3) is False

    def test_triggered_by_unique_channels(self):
        rate_limit.rate_limit_check(1, 100, "a", 10, 3)
        rate_limit.rate_limit_check(1, 200, "b", 10, 3)
        assert rate_limit.rate_limit_check(1, 300, "c", 10, 3) is True

    def test_triggered_by_same_content_in_two_channels(self):
        rate_limit.rate_limit_check(1, 100, "same text", 10, 3)
        assert rate_limit.rate_limit_check(1, 200, "same text", 10, 3) is True

    def test_not_triggered_same_channel_different_content(self):
        rate_limit.rate_limit_check(1, 100, "a", 10, 3)
        rate_limit.rate_limit_check(1, 100, "b", 10, 3)
        assert rate_limit.rate_limit_check(1, 100, "c", 10, 3) is False

    def test_max_entries_capped(self):
        for i in range(10):
            rate_limit.rate_limit_check(1, 100, f"msg {i}", 10, 3)
        assert len(rate_limit._tracker[1]) == 6


class TestClearUser:
    def test_clears_existing_user(self):
        rate_limit.rate_limit_check(1, 100, "test", 10, 3)
        assert 1 in rate_limit._tracker
        rate_limit.clear_user(1)
        assert 1 not in rate_limit._tracker

    def test_clear_nonexistent_user_does_not_raise(self):
        assert 999 not in rate_limit._tracker
        rate_limit.clear_user(999)
        assert 999 not in rate_limit._tracker


class TestPruneStaleEntries:
    def test_prune_removes_expired_entries(self):
        import time

        # Add active entry
        rate_limit.rate_limit_check(1, 100, "active", 10, 3)
        # Manually add an expired entry (older than 10 seconds)
        rate_limit.rate_limit_check(2, 200, "expired", 10, 3)
        rate_limit._tracker[2] = [(200, time.time() - 20, "expired")]

        # Prune with window_seconds = 10
        rate_limit.prune_stale_entries(window_seconds=10)

        # User 1 should remain, user 2 should be pruned
        assert 1 in rate_limit._tracker
        assert 2 not in rate_limit._tracker


class TestRateLimitGuildIsolation:
    def test_rate_limit_isolated_by_guild(self):
        # User 1 sends 2 messages in Guild 10 and 2 messages in Guild 20
        rate_limit.rate_limit_check(10, 1, 101, "msg1", 10, 3)
        rate_limit.rate_limit_check(10, 1, 102, "msg2", 10, 3)

        rate_limit.rate_limit_check(20, 1, 201, "msg3", 10, 3)
        # Guild 20 has only 2 messages (201, 202) -> should NOT trigger threshold 3
        res = rate_limit.rate_limit_check(20, 1, 202, "msg4", 10, 3)
        assert res is False

    def test_rate_limit_trips_only_in_active_guild(self):
        rate_limit.rate_limit_check(10, 1, 101, "msg1", 10, 3)
        rate_limit.rate_limit_check(10, 1, 102, "msg2", 10, 3)
        tripped_guild_10 = rate_limit.rate_limit_check(10, 1, 103, "msg3", 10, 3)
        assert tripped_guild_10 is True

        # Guild 20 for the same user is unaffected
        assert (20, 1) not in rate_limit._tracker
        check_guild_20 = rate_limit.rate_limit_check(20, 1, 201, "msg1", 10, 3)
        assert check_guild_20 is False


class TestRateLimitMemoryOptimization:
    def test_rate_limit_stores_hashes_not_raw_strings(self):
        large_content = "phishing content " * 100
        rate_limit.rate_limit_check(10, 1, 101, large_content, 10, 3)

        entries = rate_limit._tracker[(10, 1)]
        assert len(entries) == 1
        ch_id, ts, stored_content = entries[0]
        assert ch_id == 101
        assert isinstance(stored_content, int)
        assert stored_content == hash(large_content)

    def test_duplicate_content_hashes_detected(self):
        rate_limit.rate_limit_check(10, 1, 101, "identical link", 10, 3)
        tripped = rate_limit.rate_limit_check(10, 1, 102, "identical link", 10, 3)
        assert tripped is True

    def test_clear_user_by_guild(self):
        rate_limit.rate_limit_check(10, 1, 101, "test", 10, 3)
        rate_limit.rate_limit_check(20, 1, 201, "test", 10, 3)

        rate_limit.clear_user(1, guild_id=10)
        assert (10, 1) not in rate_limit._tracker
        assert (20, 1) in rate_limit._tracker

    def test_rate_limit_zero_or_negative_threshold_rejected(self):
        assert rate_limit.rate_limit_check(10, 1, 101, "msg", 10, 0) is False
        assert rate_limit.rate_limit_check(10, 1, 101, "msg", 10, -1) is False
        assert rate_limit.rate_limit_check(10, 1, 101, "msg", 0, 3) is False
        assert rate_limit.rate_limit_check(10, 1, 101, "msg", -5, 3) is False
