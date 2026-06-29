# Tsubaki — Agent Guide

Compact Discord auto-mod bot. Two source files, no tests, no CI.

## Run

```bash
uv run python src/main.py
```

All commands use `uv run` (not pip, not poetry). Ruff config in `ruff.toml` (not pyproject.toml): 120 width, double quotes, 4-space indent.

```bash
uv run ruff check src/
uv run ruff format src/
uv run ruff check --fix src/
```

## Setup

Copy `.env.example` → `.env`. Required: `DISCORD_TOKEN`. Optional: `GROQ_API_KEY` (enables `/ask`), `GROQ_MODEL` (default `openai/gpt-oss-120b`), `PORT` (starts healthcheck server).

## Architecture

- `src/main.py` — entrypoint. Slash commands: `/hello`, `/ping`, `/ask`. Syncs command tree on every startup. Healthcheck server (`/health`) runs in daemon thread only when `PORT` is set.
- `src/groq_service.py` — `GroqAskService` wraps `AsyncGroq`. Temp 0.8, max 500 tokens. System prompt sets anime-girl personality. Missing API key disables `/ask` gracefully.

## Gotchas

- Log file is `logs/logs.log` (code is truth, README is stale).
- No test suite exists — do not assume pytest or any test runner.
- `render.yaml` deploys as free web service on Render; healthcheck is mandatory there.
- Intents: default + `members=True` (Server Members Intent must be enabled in Discord Dev Portal).
- `.env` is real credentials — never commit or expose.
