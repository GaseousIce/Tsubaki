# Tsubaki

A Discord auto-moderation bot built with [discord.py](https://discordpy.readthedocs.io).

The bot is controlled with slash commands (for example, `/hello` and `/ping`).

## Prerequisites

- Python 3.10+
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- The following **Privileged Gateway Intents** must be enabled for your bot in the Developer Portal:
  - **Server Members Intent**

## Setup

```bash
git clone https://github.com/GaseousIce/Tsubaki.git
cd Tsubaki
python -m venv .
Scripts/activate
```

Then install dependencies:

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

> **Never commit your `.env` file.** It is already listed in `.gitignore`.

```bash
python src/main.py
```

## Project Structure

```
Tsubaki/
├── logs/              # Log files (not committed)
│   └── automod.log
├── src/
│   └── main.py        # Bot entry point
├── .env               # Environment variables (not committed)
├── .env.example       # Template for environment variables
├── .gitignore
├── requirements.txt
├── ruff.toml          # Ruff formatter/linter config
└── README.md
```

## Logging

Logs are written to `logs/automod.log` at INFO level; the `logs/` directory is created automatically on startup and is excluded from version control.
