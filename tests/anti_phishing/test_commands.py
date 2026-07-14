import pytest

from anti_phishing.commands import _format_duration


class TestFormatDuration:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0, "0s"),
            (86400, "1d"),
            (90000, "1d 1h"),
            (3661, "1h 1m"),
            (604800, "7d"),
            (3600, "1h"),
            (86460, "1d"),
        ],
    )
    def test_format(self, seconds, expected):
        assert _format_duration(seconds) == expected
