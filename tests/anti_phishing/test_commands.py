from anti_phishing.commands import _format_duration


class TestFormatDuration:
    def test_zero_seconds(self):
        assert _format_duration(0) == "0s"

    def test_one_day(self):
        assert _format_duration(86400) == "1d"

    def test_one_day_one_hour(self):
        assert _format_duration(90000) == "1d 1h"

    def test_one_hour_one_minute(self):
        assert _format_duration(3661) == "1h 1m"

    def test_seven_days(self):
        assert _format_duration(604800) == "7d"

    def test_only_minutes(self):
        assert _format_duration(3600) == "1h"

    def test_one_day_one_minute(self):
        assert _format_duration(86460) == "1d"
