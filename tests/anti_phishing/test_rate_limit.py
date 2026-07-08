from unittest.mock import patch

from anti_phishing import rate_limit

_RC = rate_limit.rate_limit_check
_RW = 10
_RT = 3


class TestRateLimitCheck:
    def teardown_method(self):
        rate_limit._tracker.clear()
        rate_limit._last_global_prune = 0.0

    def test_single_channel_below_threshold(self):
        result = _RC(1, 100, "https://example.com", _RW, _RT)
        assert result is False

    def test_two_channels_below_threshold(self):
        _RC(1, 100, "https://a.com", _RW, _RT)
        result = _RC(1, 200, "https://b.com", _RW, _RT)
        assert result is False

    def test_three_channels_at_threshold(self):
        _RC(1, 100, "https://a.com", _RW, _RT)
        _RC(1, 200, "https://b.com", _RW, _RT)
        result = _RC(1, 300, "https://c.com", _RW, _RT)
        assert result is True

    def test_same_content_two_channels_triggers(self):
        _RC(1, 100, "https://example.com/spam", _RW, _RT)
        result = _RC(1, 200, "https://example.com/spam", _RW, _RT)
        assert result is True

    def test_stale_entries_pruned(self):
        with patch("time.time") as mock_time:
            mock_time.return_value = 1000.0
            _RC(1, 100, "https://a.com", _RW, _RT)
            _RC(1, 200, "https://b.com", _RW, _RT)
            mock_time.return_value = 1100.0
            result = _RC(1, 300, "https://c.com", _RW, _RT)
            assert result is False

    def test_different_users_independent(self):
        _RC(1, 100, "https://a.com", _RW, _RT)
        _RC(2, 200, "https://b.com", _RW, _RT)
        _RC(2, 300, "https://c.com", _RW, _RT)
        result = _RC(2, 400, "https://d.com", _RW, _RT)
        assert result is True


class TestClearUser:
    def test_clear_existing_user(self):
        _RC(1, 100, "https://example.com", _RW, _RT)
        assert 1 in rate_limit._tracker
        rate_limit.clear_user(1)
        assert 1 not in rate_limit._tracker

    def test_clear_nonexistent_user(self):
        rate_limit.clear_user(999)
        assert 999 not in rate_limit._tracker


class TestGlobalPrune:
    def test_global_prune_removes_expired_users(self):
        with patch("time.time") as mock_time:
            mock_time.return_value = 1000.0
            _RC(1, 100, "https://a.com", _RW, _RT)
            mock_time.return_value = 10000.0
            rate_limit._last_global_prune = 0.0
            _RC(2, 200, "https://b.com", _RW, _RT)
            assert 1 not in rate_limit._tracker

    def test_entry_capping(self):
        for i in range(50):
            _RC(1, i, f"https://example.com/{i}", 1000, 3)
        assert len(rate_limit._tracker[1]) <= 6
