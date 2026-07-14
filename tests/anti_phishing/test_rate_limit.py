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


class TestClearUser:
    def test_clears_existing_user(self):
        rate_limit.rate_limit_check(1, 100, "test", 10, 3)
        assert 1 in rate_limit._tracker
        rate_limit.clear_user(1)
        assert 1 not in rate_limit._tracker

    def test_clear_nonexistent_user_does_not_raise(self):
        rate_limit.clear_user(999)
