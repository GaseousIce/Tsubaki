import tomllib

DEFAULT_ANTI_PHISHING = {
    "rate_enabled": True,
    "rate_threshold": 3,
    "rate_window": 10,
    "fetch_retries": 3,
}

DEFAULT_GROQ = {
    "model": "openai/gpt-oss-120b",
}


def load_config(path: str = "config.toml") -> dict:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    ap = DEFAULT_ANTI_PHISHING.copy()
    ap.update(data.get("anti_phishing", {}))
    gr = DEFAULT_GROQ.copy()
    gr.update(data.get("groq", {}))
    return {"anti_phishing": ap, "groq": gr}
