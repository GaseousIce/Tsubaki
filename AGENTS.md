# Tsubaki — Agent Guide

Compact Discord auto-mod bot with anti-phishing. SimCord integration tests + pure pytest unit tests.

## Run

```bash
uv run python src/main.py
```

All commands use `uv run`. Ruff config in `ruff.toml`: 120 width, double quotes, 4-space indent, lint selects E/F/I.

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run ruff check --fix src/ tests/
uv run pytest tests/ -q
uv run pytest tests/anti_phishing/ -q
```

## Setup

Copy `.env.example` → `.env`. Required: `DISCORD_TOKEN`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`. Optional: `GROQ_API_KEY` (enables `/ask`), `CLEAR_CHANNEL_ID` (enables daily 3AM auto-clear), `PORT` (starts healthcheck server at `/health`). `GROQ_MODEL` env var overrides `config.toml` model.

Missing Turso vars crash at startup (`ValueError`). Missing Groq key gracefully disables `/ask`.

## Architecture

- `src/main.py` — entrypoint. Slash commands: `/hello`, `/ping`, `/ask` (1/5s cooldown), `/clear`, `/antiphishing` (group with subcommands). Syncs command tree on every startup. Healthcheck server daemon thread only when `PORT` set. Logs to `logs/logs.log` via `RotatingFileHandler` (5 MB, 3 backups).
- `src/config.py` — `AppConfig.load()` reads `config.toml` for `[anti_phishing]` and `[groq]` sections. Pure dataclasses.
- `src/db.py` — Turso/libsql client. `migrate()` creates 4 tables (guild_configs, detection_log, custom_blocklist, typosquat_patterns). Must be called first in `setup_hook()`.
- `src/groq_service.py` — `GroqAskService` wraps `AsyncGroq`. Temp 0.8, max 500 tokens. Anime-girl personality system prompt. Model priority: `GROQ_MODEL` env var > constructor arg > config.toml > default `openai/gpt-oss-120b`.
- `src/channel_clear.py` — `/clear` slash command + optional daily auto-clear at 3AM (via `CLEAR_CHANNEL_ID`). Uses `tasks.loop`.
- `src/anti_phishing/` — 7 files:
  - `__init__.py` — `setup()` registers `on_message` listener and `/antiphishing` command group; `fetch_official_blacklist()` fetches from discord-phishing-links GitHub repo.
  - Detection pipeline: (1) official + custom blacklist → (2) typosquat pattern scan → (3) rate-limit heuristic (3+ unique channels with links in 10s). On hit: delete message, DM user, punish (timeout/kick/ban/warn), alert mod channels with interactive buttons.
  - Per-guild config stored in DB (enabled, action, timeout_duration, alert_channels, mod_roles, bypass_role, dm_message). Default: enabled, timeout 7d, no alerts.
  - Rate-limit uses in-memory dict (no Redis); auto-prunes stale entries hourly.

## Intents

Default + `members=True` + `message_content=True` (required for anti-phishing). Server Members Intent + Message Content Intent must be enabled in Discord Dev Portal.

## Testing quirks

- `libsql_client.create_client` is the only network mock (`conftest.py:mock_db` autouse). All `db.py` function bodies execute for real.
- `conftest.py:clean_globals` autouse fixture resets `domain.official`, `rate_limit._tracker`, and `db._client` between tests.
- `mock_db` fixture also sets `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` env vars so `db.get_db()` doesn't raise.
- `src/main.py` is never imported in tests — fresh `commands.Bot` instances are created via `simcord_bot` fixture, with anti-phishing + channel-clear registered.
- `simcord.assert_error` is required after slash commands that trigger `app_commands.checks` to mark expected errors as inspected.

## Gotchas

- `render.yaml` deploys as free web service on Render; healthcheck at `/health` is mandatory.
- File-based logs on Render are ephemeral. Use Render logs for live monitoring.
- `.env` is real credentials — never commit or expose.
