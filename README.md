# Tsubaki

A Discord auto-moderation bot built with [discord.py](https://discordpy.readthedocs.io).

The bot is controlled with slash commands (for example, `/hello`, `/ping`, and `/ask`).

## Prerequisites

- Python 3.10+
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- A Groq API key (for `/ask`)
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

Required environment variables:

- `DISCORD_TOKEN`: your Discord bot token
- `GROQ_API_KEY`: your Groq API key used by `/ask`
- `GROQ_MODEL` (optional): defaults to `llama-3.1-8b-instant`

```bash
python src/main.py
```

## Deploy On Render (Free)

Because Tsubaki is a Discord bot (long-running process), deploy it as a **Background Worker**, not a Web Service.

This repo includes a `render.yaml` Blueprint config for a free worker.

1. Push your code to GitHub.
2. In Render, create a new Blueprint and select this repository.
3. Render will detect `render.yaml` and create a worker service.
4. In Render service settings, set secret env vars:
    - `DISCORD_TOKEN`
    - `GROQ_API_KEY`
5. Deploy.

Notes:

- Free instances can spin down/restart; your bot reconnects when the worker is running.
- File-based logs on Render are ephemeral. Use Render logs for live monitoring.
- Keep Discord privileged intents (Server Members Intent) enabled in the Discord Developer Portal.

## Project Structure

```
Tsubaki/
├── logs/              # Log files (not committed)
│   └── automod.log
├── src/
│   ├── main.py        # Bot entry point
│   └── groq_service.py
├── .env               # Environment variables (not committed)
├── .env.example       # Template for environment variables
├── .gitignore
├── requirements.txt
├── ruff.toml          # Ruff formatter/linter config
└── README.md
```

## Logging

Logs are written to `logs/automod.log` at INFO level; the `logs/` directory is created automatically on startup and is excluded from version control.
