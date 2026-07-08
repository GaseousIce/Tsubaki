# Tsubaki

A Discord auto-moderation bot with anti-phishing, built with [discord.py](https://discordpy.readthedocs.io).

Slash commands: `/hello`, `/ping`, `/ask` (Groq AI), `/clear`, `/antiphishing` (interactive settings dashboard).

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- A Turso database URL and auth token (libSQL)
- A Groq API key (optional, for `/ask`)
- The following **Privileged Gateway Intents** must be enabled in the Developer Portal:
  - **Server Members Intent**
  - **Message Content Intent**

## Setup

```bash
git clone https://github.com/GaseousIce/Tsubaki.git
cd Tsubaki
cp .env.example .env   # then fill in your tokens
uv run python src/main.py
```

Required env vars: `DISCORD_TOKEN`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`. Optional: `GROQ_API_KEY` (enables `/ask`), `CLEAR_CHANNEL_ID` (daily 3AM auto-clear), `PORT` (healthcheck at `/health`), `GROQ_MODEL` (overrides model in `config.toml`).

## Lint & Test

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run pytest tests/ -q
```

## Deploy On Render (Free)

This repo includes a `render.yaml` Blueprint for a free web service. Because free Render services require an open HTTP port, the bot starts a tiny `/health` endpoint alongside the Discord client.

1. Push your code to GitHub.
2. In Render, create a new Blueprint and select this repository.
3. Set these secret env vars in the Render dashboard:
   - `DISCORD_TOKEN`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`
   - `GROQ_API_KEY` (optional)
   - `CLEAR_CHANNEL_ID` (optional)
4. Deploy.

On the free tier, services can spin down on inactivity — the bot reconnects when the service wakes. File-based logs are ephemeral; use Render logs for live monitoring.

## Project Structure

```
Tsubaki/
├── logs/                # Log files (ephemeral on Render)
│   └── logs.log
├── src/
│   ├── main.py          # Bot entrypoint (slash commands, healthcheck)
│   ├── config.py        # AppConfig dataclasses, reads config.toml
│   ├── db.py            # Turso/libsql client, migrations, CRUD
│   ├── groq_service.py  # AsyncGroq wrapper for /ask
│   ├── channel_clear.py # /clear command + daily auto-purge
│   └── anti_phishing/   # Detection pipeline, actions, command group
├── tests/               # Pytest + SimCord integration tests
├── .env.example         # Environment variable template
├── config.toml          # Anti-phishing and Groq settings
├── pyproject.toml       # Dependencies and pytest config
├── ruff.toml            # Linter/formatter: 120 width, double quotes
└── render.yaml          # Render Blueprint deploy config
```
