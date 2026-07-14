import tomllib
from types import SimpleNamespace


class AntiPhishingConfig(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(
            rate_enabled=kwargs.get("rate_enabled", True),
            rate_threshold=kwargs.get("rate_threshold", 3),
            rate_window=kwargs.get("rate_window", 10),
            fetch_retries=kwargs.get("fetch_retries", 3),
        )


class GroqConfig(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(
            model=kwargs.get("model", "openai/gpt-oss-120b"),
        )


class AppConfig:
    def __init__(self, data: dict):
        self.anti_phishing = AntiPhishingConfig(**data.get("anti_phishing", {}))
        self.groq = GroqConfig(**data.get("groq", {}))

    @classmethod
    def load(cls, path: str = "config.toml") -> "AppConfig":
        with open(path, "rb") as f:
            return cls(tomllib.load(f))
