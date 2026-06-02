# Tsubaki

A Discord auto-moderation bot built with [discord.py](https://discordpy.readthedocs.io).

The bot is controlled with slash commands (for example, `/hello`, `/ping`, and `/ask`).

## Prerequisites

- Python 3.12+
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- A Groq API key (for `/ask`)
- The following **Privileged Gateway Intents** must be enabled for your bot in the Developer Portal:
    - **Server Members Intent**

## Setup

Clone the repo and enter the directory:

```bash
git clone https://github.com/GaseousIce/Tsubaki.git
cd Tsubaki
```

Run the project with `uv`:

```bash
uv run python src/main.py
```

If you don't have `uv` installed, see the installation guide: https://docs.astral.sh/uv/getting-started/installation/

## Deploy On Render (Free)

Because free Render web services require an open HTTP port, this project starts a tiny `/health` endpoint and runs the Discord bot in the same process.

This repo includes a `render.yaml` Blueprint config for a free web service.

1. Push your code to GitHub.
2. In Render, create a new Blueprint and select this repository.
3. Render will detect `render.yaml` and create a web service.
4. In Render service settings, set secret env vars:
    - `DISCORD_TOKEN`
    - `GROQ_API_KEY`
5. Deploy.

Notes:

- On free tier, web services can spin down on inactivity. Your bot reconnects when the service wakes.
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
├── pyproject.toml
├── ruff.toml          # Ruff formatter/linter config
└── README.md
```

## Logging

Logs are written to `logs/automod.log` at INFO level; the `logs/` directory is created automatically on startup and is excluded from version control.
