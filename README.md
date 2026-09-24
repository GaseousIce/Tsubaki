# Tsubaki

Tsubaki is a compact Discord auto-moderation bot with anti-phishing, safe message inspection/testing, channel cleaning, a setup health check, and an optional Groq-powered `/ask` command. It runs locally with `uv` or as a Render web service with a lightweight `/health` endpoint.

## Features

### Anti-phishing

Incoming messages are checked before links can spread through a server:

1. Extract URLs from message content, embeds (titles, descriptions, fields, and footers), and attachment descriptions.
2. Match domains against the official Discord phishing and suspicious-domain lists.
3. Match against the global custom blocklist stored in Turso/libSQL and shared by every server using the database.
4. Scan configured typosquat patterns.
5. Detect link spam across 3+ unique channels within 10 seconds.
6. Delete the message, DM the user with recovery guidance, apply the configured action, and log the detection (including message text and attachment URLs/metadata) to Turso.
7. Alert configured moderator channels with interactive action buttons (**Pardon**, **Ban**, **Allowlist**), safe code-block message text previews (preventing accidental link clicks), original embed summaries, and an image grid gallery with cached attachment re-uploads (respecting payload and memory limits).
8. Enforce Discord role hierarchy checks so moderators cannot perform action overrides against members with higher or equal roles.

Supported actions are `timeout`, `kick`, `ban`, and `warn`. Defaults are enabled anti-phishing, a 7-day timeout, no alert channels, no mod roles, no bypass role, and the built-in recovery DM.

### Slash commands

| Command | Permission | Description |
| :-- | :-- | :-- |
| `/hello` | None | Say hello to Tsubaki. |
| `/ping` | None | Check bot latency. |
| `/ask <question>` | None | Ask Groq with a 1 request / 5 second per-user cooldown. Disabled when `GROQ_API_KEY` is missing. |
| `/clear [limit] [user] [bots_only]` | Manage Messages | Delete messages in the current channel with optional filters. |
| `/test <message_id>` | Manage Messages | Inspect a message by ID or link and safely log its threat status, embed summaries, and attachment previews to the log channel without taking punitive action. |
| `/setup` | Administrator | Run database, blacklist, role, permission, action, and alert-channel checks. |
| `/antiphishing settings` | Administrator | Open interactive anti-phishing settings dashboard (action, timeout duration, roles, alert channels, custom DM). |
| `/antiphishing stats` | Administrator | Show detection totals, top blocked domains, and the latest detection. |

### Optional automation

- Set `CLEAR_CHANNEL_ID` to purge that channel every day at 3:00 AM.
- Set `PORT` to start the HTTP healthcheck server on `/` and `/health` for Render.
- Set `GROQ_MODEL` to override the model in `config.toml` for `/ask`.

## Requirements

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- A Discord application with **Server Members Intent** and **Message Content Intent** enabled
- Turso/libSQL database URL and auth token

## Setup

```bash
git clone https://github.com/GaseousIce/Tsubaki.git
cd Tsubaki
cp .env.example .env
```

Edit `.env`:

```env
DISCORD_TOKEN=your_discord_bot_token
TURSO_DATABASE_URL=libsql://your-db.turso.io
TURSO_AUTH_TOKEN=your-token

# Optional
GROQ_API_KEY=your-groq-key
GROQ_MODEL=openai/gpt-oss-120b
CLEAR_CHANNEL_ID=123456789012345678
PORT=10000
```

`DISCORD_TOKEN`, `TURSO_DATABASE_URL`, and `TURSO_AUTH_TOKEN` are required. Missing Turso values fail startup; missing `GROQ_API_KEY` only disables `/ask`.

## Run

```bash
uv run python src/main.py
```

On startup Tsubaki runs database migrations, loads the official phishing lists, registers slash commands, and syncs the command tree with Discord.

## Development

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run ruff check --fix src/ tests/
uv run pytest tests/ -q
uv run pytest tests/anti_phishing/ -q
uv run pytest tests/e2e/ -q
uv run pytest -m "not network" -q
```

Ruff uses a 120-character line length, double quotes, 4-space indents, and E/F/I lint rules.

## Project structure

```text
Tsubaki/
├── src/
│   ├── main.py              # Entrypoint, bot lifecycle, graceful shutdown, healthcheck server
│   ├── commands.py          # /hello, /ping, /ask, and /test commands
│   ├── setup.py             # /setup health and permissions check
│   ├── channel_clear.py     # /clear and optional daily purge
│   ├── config.py            # config.toml loader
│   ├── db.py                # Turso/libSQL client, migrations, CRUD helpers
│   ├── groq_service.py      # Groq /ask client wrapper
│   └── anti_phishing/       # Detection pipeline, interactive UI, actions, domains
│       ├── __init__.py      # Listener setup, background tasks, slash group
│       ├── actions.py       # Detection handler, image gallery alerts, interactive buttons
│       ├── commands.py      # /antiphishing settings dashboard and stats
│       ├── domain.py        # URL parsing, official list fetching, typosquatting
│       └── rate_limit.py    # Channel-spread rate limiter and auto-pruning
├── tests/                   # Pytest and SimCord unit, integration, and E2E tests
│   ├── anti_phishing/       # Anti-phishing action, command, domain, and lifecycle tests
│   ├── e2e/                 # Multi-tier end-to-end and adversarial scenario tests
│   ├── conftest.py          # SimCord fixtures, DB mocks, state resets
│   ├── test_bot_commands.py # Tests for basic and AI slash commands (/hello, /ping, /ask, /test)
│   ├── test_channel_clear.py# Tests for /clear command and daily purge loop
│   ├── test_config.py       # Tests for config loading
│   ├── test_db.py           # Tests for Turso migrations and CRUD helpers
│   ├── test_groq.py         # Tests for Groq integration
│   ├── test_main.py         # Tests for bot lifecycle and graceful shutdown
│   └── test_setup.py        # Tests for /setup health check
├── config.toml              # Anti-phishing and Groq defaults
├── render.yaml              # Render web service blueprint
├── ruff.toml                # Ruff configuration
└── pyproject.toml           # Project metadata and dependencies
```

## Render deployment

1. Push your fork to GitHub.
2. Create a Render Blueprint from `render.yaml`.
3. Add `DISCORD_TOKEN`, `TURSO_DATABASE_URL`, and `TURSO_AUTH_TOKEN`.
4. Optionally add `GROQ_API_KEY`, `GROQ_MODEL`, and `CLEAR_CHANNEL_ID`.
5. Deploy.

Render uses `/health` as the healthcheck path. File logs in `logs/logs.log` are local/ephemeral on Render, so use Render logs for live debugging.
