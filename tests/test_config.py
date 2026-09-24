from dataclasses import asdict

import pytest

from config import AntiPhishingConfig, AppConfig, GroqConfig, load_config


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


class TestConfigValidation:
    def test_invalid_rate_threshold_zero(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[anti_phishing]\nrate_threshold = 0\n")
        with pytest.raises(ValueError, match="rate_threshold"):
            load_config(str(p))

    def test_invalid_rate_threshold_negative(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[anti_phishing]\nrate_threshold = -2\n")
        with pytest.raises(ValueError, match="rate_threshold"):
            load_config(str(p))

    def test_invalid_rate_threshold_type(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[anti_phishing]\nrate_threshold = 'three'\n")
        with pytest.raises(ValueError, match="rate_threshold"):
            load_config(str(p))

    def test_invalid_rate_threshold_bool(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[anti_phishing]\nrate_threshold = true\n")
        with pytest.raises(ValueError, match="rate_threshold"):
            load_config(str(p))

    def test_invalid_rate_window_zero(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[anti_phishing]\nrate_window = 0\n")
        with pytest.raises(ValueError, match="rate_window"):
            load_config(str(p))

    def test_invalid_rate_window_negative(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[anti_phishing]\nrate_window = -10.5\n")
        with pytest.raises(ValueError, match="rate_window"):
            load_config(str(p))

    def test_invalid_rate_window_type(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[anti_phishing]\nrate_window = '10s'\n")
        with pytest.raises(ValueError, match="rate_window"):
            load_config(str(p))

    def test_invalid_fetch_retries_negative(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[anti_phishing]\nfetch_retries = -1\n")
        with pytest.raises(ValueError, match="fetch_retries"):
            load_config(str(p))

    def test_invalid_fetch_retries_type(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[anti_phishing]\nfetch_retries = false\n")
        with pytest.raises(ValueError, match="fetch_retries"):
            load_config(str(p))

    def test_invalid_rate_enabled_type(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[anti_phishing]\nrate_enabled = 1\n")
        with pytest.raises(ValueError, match="rate_enabled"):
            load_config(str(p))

    def test_invalid_groq_model_empty(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[groq]\nmodel = ''\n")
        with pytest.raises(ValueError, match="groq.model"):
            load_config(str(p))

    def test_invalid_groq_model_whitespace(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[groq]\nmodel = '   '\n")
        with pytest.raises(ValueError, match="groq.model"):
            load_config(str(p))

    def test_invalid_groq_model_type(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[groq]\nmodel = 123\n")
        with pytest.raises(ValueError, match="groq.model"):
            load_config(str(p))

    def test_invalid_section_not_table(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("anti_phishing = 'invalid'\n")
        with pytest.raises(ValueError, match="'anti_phishing' section must be a table"):
            load_config(str(p))

    def test_unknown_section_raises(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[unknown_section]\nfoo = 'bar'\n")
        with pytest.raises(ValueError, match="Unknown configuration section"):
            load_config(str(p))

    def test_unknown_key_in_anti_phishing_raises(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[anti_phishing]\nrate_treshold = 5\n")
        with pytest.raises(ValueError, match="Unknown configuration key"):
            load_config(str(p))

    def test_unknown_key_in_groq_raises(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[groq]\nextra_key = 'value'\n")
        with pytest.raises(ValueError, match="Unknown configuration key in \\[groq\\]"):
            load_config(str(p))

    def test_invalid_groq_section_not_table(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("groq = 123\n")
        with pytest.raises(ValueError, match="'groq' section must be a table"):
            load_config(str(p))


class TestAppConfigDataclass:
    def test_app_config_load_returns_dataclass(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[anti_phishing]\nrate_threshold = 4\n[groq]\nmodel = 'my-model'\n")
        cfg = AppConfig.load(str(p))
        assert isinstance(cfg, AppConfig)
        assert isinstance(cfg.anti_phishing, AntiPhishingConfig)
        assert isinstance(cfg.groq, GroqConfig)
        assert cfg.anti_phishing.rate_threshold == 4
        assert cfg.anti_phishing.rate_enabled is True
        assert cfg.groq.model == "my-model"

    def test_app_config_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            AppConfig.load("nonexistent_path.toml")

    def test_app_config_dict_access(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("")
        cfg = AppConfig.load(str(p))
        assert cfg["anti_phishing"]["rate_threshold"] == 3
        assert cfg.get("groq")["model"] == "openai/gpt-oss-120b"
        assert cfg["anti_phishing"].get("rate_threshold") == 3
        with pytest.raises(KeyError):
            _ = cfg["invalid"]

    def test_asdict_export(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("")
        cfg = AppConfig.load(str(p))
        d = asdict(cfg)
        assert d == {
            "anti_phishing": {
                "rate_enabled": True,
                "rate_threshold": 3,
                "rate_window": 10,
                "fetch_retries": 3,
            },
            "groq": {
                "model": "openai/gpt-oss-120b",
            },
        }
