# Tsubaki

Tsubaki is a high-performance, lightweight Discord auto-moderation bot featuring robust anti-phishing protection, an interactive administration dashboard, channel cleaning tools, and a Groq AI-powered chat command. It is designed to run efficiently on local environments or deploy seamlessly to cloud providers like Render.

---

## Features

### 🛡️ Anti-Phishing & Security Pipeline

Tsubaki implements a multi-stage security pipeline to detect and mitigate phishing links before they can compromise your community:

1. **Domain Extraction**: Scans all incoming message content and message embeds for URLs.
2. **Blacklist Validation**: Matches extracted domains against:
   - The community-curated [official phishing links database](https://github.com/nikolaischunk/discord-phishing-links).
   - A per-server **Custom Blocklist** stored in the database.
3. **Cross-Channel Rate-Limit Heuristic**: Automatically detects spam/phishing spreads across multiple channels (triggers when a user sends links/content across 3+ unique channels within a 10-second window).
4. **Automated Punishment Actions**: Servers can configure the pipeline to automatically **Timeout**, **Kick**, **Ban**, or **Warn** offending accounts.
5. **Interactive Mod Alerts**: Alerts moderators in designated channels with interactive button components:
   - **Pardon User**: Instantly removes timeouts.
   - **Ban User**: Escalates the punishment to a permanent ban.
   - **Allow URL**: Removes the domain from the blocklist if it was flagged in error.
6. **Compromised Account Security DMs**: Automatically direct-messages the offender with step-by-step account recovery instructions (changing password, enabling 2FA, revoking unauthorized apps, regenerating token).

### 🤖 Groq AI Assistant (`/ask`)

- Integrates Groq's high-speed LLM SDK to answer user questions using an anime-girl persona.
- Respects a global **5-second cooldown** per user to prevent API quota exhaustion.
- Gracefully disables itself if no API key is configured.

### 🧹 Channel Purging & Maintenance (`/clear`)

- Clean channel history with customizable filters:
  - **Limit**: Specific number of messages to delete.
  - **User**: Only clear messages sent by a particular member.
  - **Bots Only**: Only clear messages sent by bots.
- **Daily Automated Purge**: Clears a specified channel daily at 3:00 AM if `CLEAR_CHANNEL_ID` is set in the environment.

---

## Slash Commands

| Command                             | Permissions       | Description                                               |
| :---------------------------------- | :---------------- | :-------------------------------------------------------- |
| `/hello`                            | None              | Say hello to Tsubaki.                                     |
| `/ping`                             | None              | Verify bot latency and status.                            |
| `/ask <question>`                   | None              | Ask Tsubaki anything (cooldown: 1 request per 5 seconds). |
| `/clear [limit] [user] [bots_only]` | `Manage Messages` | Purge messages with optional filters.                     |
| `/antiphishing settings`            | `Administrator`   | Open the interactive settings dashboard.                  |
| `/antiphishing stats`               | `Administrator`   | View server-specific phishing detection metrics and logs. |

---

## Technical Stack

- **Runtime**: [Python 3.12+](https://www.python.org/)
- **Framework**: [discord.py](https://discordpy.readthedocs.io) (v2.7+)
- **Database**: [Turso](https://turso.tech/) / [libSQL](https://github.com/tursodatabase/libsql) (SQLite-compatible edge database)
- **AI Core**: [Groq Python SDK](https://github.com/groq/groq-python)
- **Package Manager**: [uv](https://docs.astral.sh/uv/) (Astral)
- **Linter & Formatter**: [Ruff](https://docs.astral.sh/ruff/) (120 character width, double quotes, 4-space indent)
- **Testing**: [pytest](https://docs.pytest.org/), [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio), and [simcord](https://simcord.readthedocs.io/en/latest/) (Discord integration testing library)

---

## Setup & Local Running

### 1. Prerequisites

- A Discord Developer Application with **Server Members** and **Message Content** privileged intents enabled.
- A Turso Database (or local SQLite file) and Auth Token.
- An Astral `uv` installation.

### 2. Installation

Clone the repository and initialize the environment:

```bash
git clone https://github.com/GaseousIce/Tsubaki.git
cd Tsubaki
cp .env.example .env
```

### 3. Configuration

Configure the `.env` file with your credentials:

```env
# Required Credentials
DISCORD_TOKEN=your_discord_bot_token_here
TURSO_DATABASE_URL=your_turso_db_url_here
TURSO_AUTH_TOKEN=your_turso_auth_token_here

# Optional Features
GROQ_API_KEY=your_groq_api_key_here
CLEAR_CHANNEL_ID=your_daily_clear_channel_id_here
PORT=10000
```

- _Note: Missing Turso credentials will cause the bot to raise a `ValueError` on startup. A missing Groq key will disable `/ask` gracefully._

### 4. Run the Bot

Tsubaki handles migrations and blacklist fetching automatically on startup.

```bash
uv run python src/main.py
```

---

## Development, Quality, and Testing

Tsubaki uses `ruff` for code style validation and formatting, and `pytest` alongside `simcord` for full integration coverage.

### Code Style (Linter & Formatter)

```bash
# Check code style and rules
uv run ruff check src/ tests/

# Automatically apply safe fixes
uv run ruff check --fix src/ tests/

# Format code
uv run ruff format src/ tests/
```

### Testing Suite

```bash
# Run all unit and integration tests
uv run pytest tests/ -q

# Run anti-phishing tests only
uv run pytest tests/anti_phishing/ -q
```

---

## Project Structure

```
Tsubaki/
├── .agents/             # Agent guidelines and customization workspace
├── logs/                # Local log folder (logs.log rotates at 5 MB, keeps 3 backups)
├── src/
│   ├── main.py          # Application entrypoint and healthcheck HTTP daemon
│   ├── config.py        # Settings loader parsing config.toml
│   ├── db.py            # Turso client interface, migrations, and CRUD
│   ├── groq_service.py  # Groq API client interface with anime persona prompt
│   ├── channel_clear.py # Channel purge logic and daily 3:00 AM Cron task
│   └── anti_phishing/   # Core anti-phishing module
│       ├── __init__.py  # Pipeline routing & event listener setup
│       ├── actions.py   # Punishments, mod alerts, and user DM builders
│       ├── commands.py  # Settings dashboard GUI & stats slash commands
│       ├── domain.py    # URL extractor & blacklists (community + custom)
│       └── rate_limit.py# In-memory user cross-channel rate-limit tracker
├── tests/               # Pytest test suites and SimCord mock clients
├── config.toml          # Default configuration parameters (fetch retries, thresholds, LLM model)
├── pyproject.toml       # Project metadata and dependencies declaration
├── render.yaml          # Infrastructure-as-code for Render Blueprint deployments
└── ruff.toml            # Ruff linter specifications
```

---

## Deploying to Render (Free Web Service)

Tsubaki includes a `render.yaml` configuration to allow quick deployments on Render:

1. Push your repository fork to GitHub.
2. In the Render Dashboard, go to **Blueprints** and connect this repository.
3. Supply the environment variables in the dashboard: `DISCORD_TOKEN`, `TURSO_DATABASE_URL`, and `TURSO_AUTH_TOKEN`. Optionally supply `GROQ_API_KEY` and `CLEAR_CHANNEL_ID`.
4. Deploy the blueprint.

Because free-tier web services on Render require binding to a port and responding to HTTP requests, Tsubaki starts a lightweight `/health` check server in a background daemon thread listening on port `$PORT` (defaulting to 10000) to keep the service healthy. File-based logs on Render are ephemeral; utilize the Render console logs for live monitoring.
