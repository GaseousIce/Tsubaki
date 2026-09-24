import tomllib
from dataclasses import asdict, dataclass, field
from typing import Any

DEFAULT_ANTI_PHISHING = {
    "rate_enabled": True,
    "rate_threshold": 3,
    "rate_window": 10,
    "fetch_retries": 3,
}

DEFAULT_GROQ = {
    "model": "openai/gpt-oss-120b",
}


@dataclass
class AntiPhishingConfig:
    rate_enabled: bool = True
    rate_threshold: int = 3
    rate_window: int | float = 10
    fetch_retries: int = 3

    def __post_init__(self) -> None:
        if not isinstance(self.rate_enabled, bool):
            raise ValueError(f"rate_enabled must be a bool, got {type(self.rate_enabled).__name__}")
        if isinstance(self.rate_threshold, bool) or not isinstance(self.rate_threshold, int) or self.rate_threshold < 1:
            raise ValueError(f"rate_threshold must be an integer >= 1, got {self.rate_threshold!r}")
        if (
            isinstance(self.rate_window, bool)
            or not isinstance(self.rate_window, (int, float))
            or self.rate_window <= 0
        ):
            raise ValueError(f"rate_window must be a positive number (> 0), got {self.rate_window!r}")
        if isinstance(self.fetch_retries, bool) or not isinstance(self.fetch_retries, int) or self.fetch_retries < 0:
            raise ValueError(f"fetch_retries must be an integer >= 0, got {self.fetch_retries!r}")

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass
class GroqConfig:
    model: str = "openai/gpt-oss-120b"

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError(f"groq.model must be a non-empty string, got {self.model!r}")

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass
class AppConfig:
    anti_phishing: AntiPhishingConfig = field(default_factory=AntiPhishingConfig)
    groq: GroqConfig = field(default_factory=GroqConfig)

    def __getitem__(self, key: str) -> Any:
        if key == "anti_phishing":
            return self.anti_phishing
        if key == "groq":
            return self.groq
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @classmethod
    def load(cls, path: str = "config.toml") -> "AppConfig":
        with open(path, "rb") as f:
            data = tomllib.load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Configuration root must be a table, got {type(data).__name__}")

        # Validate sections
        for section in data:
            if section not in {"anti_phishing", "groq"}:
                raise ValueError(f"Unknown configuration section: {section!r}")

        ap_data = data.get("anti_phishing", {})
        if not isinstance(ap_data, dict):
            raise ValueError(f"'anti_phishing' section must be a table, got {type(ap_data).__name__}")

        for k in ap_data:
            if k not in {"rate_enabled", "rate_threshold", "rate_window", "fetch_retries"}:
                raise ValueError(f"Unknown configuration key in [anti_phishing]: {k!r}")

        gr_data = data.get("groq", {})
        if not isinstance(gr_data, dict):
            raise ValueError(f"'groq' section must be a table, got {type(gr_data).__name__}")

        for k in gr_data:
            if k not in {"model"}:
                raise ValueError(f"Unknown configuration key in [groq]: {k!r}")

        return cls(
            anti_phishing=AntiPhishingConfig(**ap_data),
            groq=GroqConfig(**gr_data),
        )


def load_config(path: str = "config.toml") -> dict:
    app_cfg = AppConfig.load(path)
    return {
        "anti_phishing": asdict(app_cfg.anti_phishing),
        "groq": asdict(app_cfg.groq),
    }
