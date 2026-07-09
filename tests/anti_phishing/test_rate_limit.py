import time

from anti_phishing import rate_limit


class TestRateLimitPrune:
    def test_partial_prune_keeps_valid_entries(self):
        """Global prune keeps entries where some are valid and some expired."""
        now = time.time()
        rate_limit._last_global_prune = 0.0
        rate_limit._tracker.clear()

        # Two users: one with all stale entries, one with mixed (some stale, some fresh).
        rate_limit._tracker[1] = [
            (10, now - 10000, "hash_a"),
            (11, now - 10000, "hash_b"),
        ]
        rate_limit._tracker[2] = [
            (20, now - 10000, "hash_c"),
            (21, now - 100, "hash_d"),
        ]

        # This triggers the global prune in rate_limit_check.
        # rate_window=3600, rate_threshold=3 — won't trigger rate limit.
        rate_limit.rate_limit_check(2, 30, "fresh content", 3600, 3)

        # User 1 had all expired → removed.
        assert 1 not in rate_limit._tracker

        # User 2 had 1 expired + 1 valid → kept: 1 valid original + 1 new from this call.
        assert 2 in rate_limit._tracker
        assert len(rate_limit._tracker[2]) == 2
