import tomllib
from dataclasses import dataclass, field


@dataclass
class AntiPhishingConfig:
    rate_enabled: bool = True
    rate_threshold: int = 3
    rate_window: int = 10
    fetch_retries: int = 3


@dataclass
class AppConfig:
    anti_phishing: AntiPhishingConfig = field(default_factory=AntiPhishingConfig)

    @classmethod
    def load(cls, path: str = "config.toml") -> "AppConfig":
        with open(path, "rb") as f:
            data = tomllib.load(f)
        ap = data.get("anti_phishing", {})
        return cls(anti_phishing=AntiPhishingConfig(**ap))
