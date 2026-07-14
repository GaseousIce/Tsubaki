import pytest

from config import AntiPhishingConfig, AppConfig, GroqConfig


class TestAntiPhishingConfig:
    def test_defaults(self):
        cfg = AntiPhishingConfig()
        assert cfg.rate_enabled is True
        assert cfg.rate_threshold == 3
        assert cfg.rate_window == 10
        assert cfg.fetch_retries == 3

    def test_custom_values(self):
        cfg = AntiPhishingConfig(rate_enabled=False, rate_threshold=5, rate_window=20, fetch_retries=1)
        assert cfg.rate_enabled is False
        assert cfg.rate_threshold == 5
        assert cfg.rate_window == 20
        assert cfg.fetch_retries == 1


class TestGroqConfig:
    def test_default_model(self):
        cfg = GroqConfig()
        assert cfg.model == "openai/gpt-oss-120b"

    def test_custom_model(self):
        cfg = GroqConfig(model="mixtral-8x7b")
        assert cfg.model == "mixtral-8x7b"


class TestAppConfig:
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

        cfg = AppConfig.load(str(config_path))
        assert cfg.anti_phishing.rate_enabled is False
        assert cfg.anti_phishing.rate_threshold == 5
        assert cfg.anti_phishing.rate_window == 15
        assert cfg.anti_phishing.fetch_retries == 2
        assert cfg.groq.model == "test-model"

    def test_load_missing_sections(self, tmp_path):
        toml_content = ""
        config_path = tmp_path / "config.toml"
        config_path.write_text(toml_content)

        cfg = AppConfig.load(str(config_path))
        assert cfg.anti_phishing.rate_enabled is True
        assert cfg.anti_phishing.rate_threshold == 3
        assert cfg.groq.model == "openai/gpt-oss-120b"

    def test_load_partial_anti_phishing(self, tmp_path):
        toml_content = """
[anti_phishing]
rate_enabled = false
"""
        config_path = tmp_path / "config.toml"
        config_path.write_text(toml_content)

        cfg = AppConfig.load(str(config_path))
        assert cfg.anti_phishing.rate_enabled is False
        assert cfg.anti_phishing.rate_threshold == 3
        assert cfg.groq.model == "openai/gpt-oss-120b"

    def test_load_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            AppConfig.load("nonexistent_config.toml")
