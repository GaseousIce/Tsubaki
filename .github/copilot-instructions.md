# Copilot Instructions for Tsubaki

Discord auto-mod bot with anti-phishing. Python 3.12+, discord.py, uv.

## Run

```bash
uv run python src/main.py
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run ruff check --fix src/ tests/
uv run pytest tests/ -q
uv run pytest -m "not network" -q
```

Ruff in `ruff.toml`: 120 width, double quotes, 4-space indent, lint E/F/I.

## Env

Copy `.env.example` → `.env`. Required: `DISCORD_TOKEN`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`. Optional: `GROQ_API_KEY` (enables `/ask`), `GROQ_MODEL` (overrides config.toml model), `CLEAR_CHANNEL_ID` (daily 3AM auto-clear), `PORT` (healthcheck at `/health`).

Missing Turso vars crash at startup. Missing Groq key gracefully disables `/ask`.

## Structure

- `main.py` — entrypoint, bot lifecycle (`setup_hook`, `on_ready`), healthcheck daemon thread on `PORT`, fallback on DB failure.
- `commands.py` — slash commands `/hello`, `/ping`, `/ask` (1/5s cooldown, anime-girl personality).
- `setup.py` — `/setup` command checking bot permissions, role hierarchy, DB, blacklist, and alert channels.
- `config.py` — `AppConfig.load()` reads `config.toml`.
- `db.py` — Turso/libsql client. `migrate()` creates 4 tables (`guild_configs`, `detection_log`, `custom_blocklist`, `typosquat_patterns`) and migrates `content` and `attachments` columns on `detection_log`. In-memory config cache with eviction.
- `groq_service.py` — `GroqAskService` wraps `AsyncGroq`. Temp 0.8, max 500 tokens. Anime-girl system prompt.
- `channel_clear.py` — `/clear` command (supports `limit`, `user`, `bots_only`) + daily 3AM auto-clear via `tasks.loop`.
- `anti_phishing/` — 5 files:
  - `__init__.py`: setup, event listeners, background tasks (`prune_rate_limits`, `recover_database`), command group (`settings`, `stats`).
  - `actions.py`: detection handling, attachment metadata extraction, user DM, punishment (`timeout`/`kick`/`ban`/`warn`), mod alerts with content & embed previews, interactive buttons (`PhishingAlertView`).
  - `commands.py`: `/antiphishing settings` dashboard and `/antiphishing stats`.
  - `domain.py`: URL extraction from text, embeds, and attachments; official blacklist fetching, typosquatting checks.
  - `rate_limit.py`: multi-channel link spam tracker (3+ channels in 10s), hourly stale entry pruning.

## Intents

Default + `members=True` + `message_content=True`. Server Members + Message Content intents must be enabled in Discord Dev Portal.

## Error Handling

- Missing `DISCORD_TOKEN`: fatal `ValueError`.
- Missing `GROQ_API_KEY`: `/ask` gracefully disabled.
- Groq API errors: logged, user gets retry message.
- AI responses > 2000 chars: truncated with `...`.
- All slash handlers async; long ops use deferred response.
