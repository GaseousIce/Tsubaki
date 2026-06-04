# Copilot Instructions for Tsubaki

## Project Overview

Tsubaki is a Discord auto-moderation bot built with discord.py. It provides slash commands for user interaction and integrates with Groq's API for AI-powered responses.

**Key Technologies:**
- discord.py (async Discord bot framework)
- Groq API (for `/ask` AI responses)
- Python 3.12+
- uv (package manager)

## Build, Test & Linting

### Running the Bot

```bash
# Run the bot locally
uv run python src/main.py

# The bot starts a health check HTTP server on port 10000 (configurable via PORT env var)
```

### Linting and Formatting

Ruff is configured for linting and formatting. Configuration is in `ruff.toml`:
- Line length: 120 characters
- Quote style: double quotes
- Indent: 4 spaces
- Enabled rules: E (pycodestyle errors), F (pyflakes), I (isort)

```bash
# Check for linting issues
uv run ruff check src/

# Format code
uv run ruff format src/

# Both check and format
uv run ruff check --fix src/
```

### Environment Setup

Copy `.env.example` to `.env` and populate:
- `DISCORD_TOKEN` - Discord bot token (required)
- `GROQ_API_KEY` - API key for Groq AI (required for `/ask` command)
- `GROQ_MODEL` - AI model (defaults to `openai/gpt-oss-120b`)
- `PORT` - HTTP health check port (defaults to 10000, only used if set)

## Architecture

### Core Structure

- **`src/main.py`** - Bot entry point
  - Initializes Discord intents (with Server Members Intent enabled)
  - Registers slash commands: `/hello`, `/ping`, `/ask`
  - Starts healthcheck HTTP server in background (for Render.com deployment)
  - Syncs commands with Discord on startup
  - Handles logging to `logs/logs.log`

- **`src/groq_service.py`** - Groq AI integration
  - `GroqAskService` wraps the Groq async API
  - Configurable via `GROQ_API_KEY` and `GROQ_MODEL` env vars
  - System prompt establishes "Tsubaki" personality (cute anime-girl vibe with weeb slang)
  - Response truncated to Discord's 2000-char limit
  - Temperature: 0.8, max tokens: 500

### Slash Commands

1. **`/hello`** - Simple greeting, always available
2. **`/ping`** - Returns bot latency in ms
3. **`/ask [question]`** - AI-powered response via Groq (disabled if `GROQ_API_KEY` not set)

### Deployment (Render.com)

The project includes `render.yaml` for free Render.com deployment:
- Starts HTTP healthcheck server (required for free tier to keep service alive)
- Logs written to `logs/logs.log` (ephemeral on Render)
- Recreates bot connection on service wake-up

## Key Conventions

### Logging

- All logs go to `logs/logs.log` at INFO level (DEBUG during bot runtime)
- Discord library logs are prefixed with "discord"
- Healthcheck server requests are silenced (no logs)

### Error Handling

- Missing `DISCORD_TOKEN` raises `ValueError` at startup (fatal)
- Missing `GROQ_API_KEY` gracefully disables `/ask` with warning
- Groq API errors are logged and user receives error message (command can retry)
- Long AI responses truncated with `...` to fit Discord's 2000 char limit

### Async Patterns

- All Groq API calls use `AsyncGroq` for non-blocking I/O
- Slash command handlers are async; deferred responses for long operations (`/ask`)
- Healthcheck server runs in daemon thread (doesn't block bot shutdown)

### Discord Configuration

- **Intents**: Default intents + `members=True` (Server Members Intent required)
- **Command type**: Slash commands (app commands)
- **Command prefix**: Mentions only (commands are slash-based)
