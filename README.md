# automod-bot

A Discord auto-moderation bot built with [discord.py](https://discordpy.readthedocs.io).

## Prerequisites

- Python 3.10+
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))

## Setup

```bash
git clone https://github.com/GaseousIce/Tsubaki.git
cd automod-bot
python -m venv .
Scripts/activate

pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
DISCORD_TOKEN=your_bot_token_here
```

> **Never commit your `.env` file.** It is already listed in `.gitignore`.

```bash
python src/main.py
```

## Project Structure

```
automod-bot/
├── logs/              # Log files (not committed)
│   └── automod.log
├── src/
│   └── main.py        # Bot entry point
├── .env               # Environment variables (not committed)
├── .gitignore
├── requirements.txt
├── ruff.toml          # Ruff formatter/linter config
└── README.md
```

## Logging

Logs are written to `logs/automod.log`. The `logs/` directory is created automatically on startup and is excluded from version control.
