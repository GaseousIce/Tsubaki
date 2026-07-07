# Copilot Instructions for Tsubaki

Discord auto-mod bot with anti-phishing. Python 3.12+, discord.py, uv.

## Run

```bash
uv run python src/main.py
uv run ruff check src/
uv run ruff format src/
uv run ruff check --fix src/
```

Ruff in `ruff.toml`: 120 width, double quotes, 4-space indent, lint E/F/I.

## Env

Copy `.env.example` → `.env`. Required: `DISCORD_TOKEN`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`. Optional: `GROQ_API_KEY` (enables `/ask`), `GROQ_MODEL` (overrides config.toml model), `CLEAR_CHANNEL_ID` (daily 3AM auto-clear), `PORT` (healthcheck at `/health`).

Missing Turso vars crash at startup. Missing Groq key gracefully disables `/ask`.

## Structure

- `main.py` — entrypoint. Slash commands: `/hello`, `/ping`, `/ask` (1/5s cooldown), `/clear`, `/antiphishing` (group with subcommands). Syncs tree on startup. Healthcheck daemon thread only when `PORT` set. Logs to `logs/logs.log` (RotatingFileHandler, 5 MB, 3 backups).
- `config.py` — `AppConfig.load()` reads `config.toml`.
- `db.py` — Turso/libsql client. `migrate()` creates 4 tables; must be called first in `setup_hook()`.
- `groq_service.py` — `GroqAskService` wraps `AsyncGroq`. Temp 0.8, max 500 tokens. Anime-girl system prompt.
- `channel_clear.py` — `/clear` command + daily 3AM auto-clear via `tasks.loop`.
- `anti_phishing/` — 7 files. Detection pipeline: (1) official + custom blacklist, (2) typosquat patterns, (3) rate-limit heuristic (3+ channels in 10s). On hit: delete → DM → punish (timeout/kick/ban/warn) → alert mod channels. Per-guild config in DB. Rate-limit in-memory, prunes hourly.

## Intents

Default + `members=True` + `message_content=True`. Server Members + Message Content intents must be enabled in Discord Dev Portal.

## Error Handling

- Missing `DISCORD_TOKEN`: fatal `ValueError`.
- Missing `GROQ_API_KEY`: `/ask` gracefully disabled.
- Groq API errors: logged, user gets retry message.
- AI responses > 2000 chars: truncated with `...`.
- All slash handlers async; long ops use deferred response.
