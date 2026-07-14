import pytest

from config import load_config


class TestLoadConfig:
    def test_load_valid_config(self, tmp_path):
        toml_content = """
[anti_phishing]
rate_enabled = false
rate_threshold = 5
rate_window = 15
fetch_retries = 2

[groq]
model = "test-model"
"""
        config_path = tmp_path / "config.toml"
        config_path.write_text(toml_content)

        cfg = load_config(str(config_path))
        assert cfg["anti_phishing"]["rate_enabled"] is False
        assert cfg["anti_phishing"]["rate_threshold"] == 5
        assert cfg["anti_phishing"]["rate_window"] == 15
        assert cfg["anti_phishing"]["fetch_retries"] == 2
        assert cfg["groq"]["model"] == "test-model"

    def test_load_missing_sections_uses_defaults(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text("")

        cfg = load_config(str(config_path))
        assert cfg["anti_phishing"]["rate_enabled"] is True
        assert cfg["anti_phishing"]["rate_threshold"] == 3
        assert cfg["groq"]["model"] == "openai/gpt-oss-120b"

    def test_load_partial_anti_phishing(self, tmp_path):
        toml_content = """
[anti_phishing]
rate_enabled = false
"""
        config_path = tmp_path / "config.toml"
        config_path.write_text(toml_content)

        cfg = load_config(str(config_path))
        assert cfg["anti_phishing"]["rate_enabled"] is False
        assert cfg["anti_phishing"]["rate_threshold"] == 3
        assert cfg["groq"]["model"] == "openai/gpt-oss-120b"

    def test_load_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_config("nonexistent_config.toml")
