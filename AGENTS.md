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
uv run pytest -m "not network" -q
```

## Setup

Copy `.env.example` → `.env`. Required: `DISCORD_TOKEN`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`. Optional: `GROQ_API_KEY` (enables `/ask`), `CLEAR_CHANNEL_ID` (enables daily 3AM auto-clear), `PORT` (starts healthcheck server at `/health`). `GROQ_MODEL` env var overrides `config.toml` model.

Missing Turso vars crash at startup (`ValueError`). Missing Groq key gracefully disables `/ask`.

## Architecture

- `src/main.py` — entrypoint and bot lifecycle (`setup_hook`, `on_ready`). Syncs command tree on every startup. Healthcheck server daemon thread only when `PORT` set. Recovers gracefully if DB migration fails at startup. Logs to `logs/logs.log` via `RotatingFileHandler` (5 MB, 3 backups).
- `src/commands.py` — basic and AI slash commands: `/hello`, `/ping`, `/ask` (1/5s cooldown, anime-girl personality, graceful fallback when `GROQ_API_KEY` missing).
- `src/setup.py` — `/setup` slash command (administrator only) checking bot role position, guild permissions, action readiness, alert channel permissions, DB connectivity, and official blacklist status.
- `src/config.py` — `AppConfig.load()` reads `config.toml` for `[anti_phishing]` and `[groq]` sections. Pure dataclasses.
- `src/db.py` — Turso/libsql client. `migrate()` creates 4 tables (`guild_configs`, `detection_log`, `custom_blocklist`, `typosquat_patterns`) and dynamically migrates `content` and `attachments` columns on `detection_log`. In-memory guild config cache with eviction. `log_detection()` stores full message text and attachment URLs. Must be called first in `setup_hook()`.
- `src/groq_service.py` — `GroqAskService` wraps `AsyncGroq`. Temp 0.8, max 500 tokens. Anime-girl personality system prompt. Model priority: `GROQ_MODEL` env var > constructor arg > config.toml > default `openai/gpt-oss-120b`.
- `src/channel_clear.py` — `/clear` slash command (Manage Messages, optional `limit`, `user`, `bots_only` filters) + optional daily auto-clear at 3AM (via `CLEAR_CHANNEL_ID`). Uses `tasks.loop`.
- `src/anti_phishing/` — 5 files:
  - `__init__.py` — `setup()` registers `on_message` listener, `on_ready` / `on_guild_join` lifecycle handlers, periodic background tasks (`prune_rate_limits`, `recover_database`), and `/antiphishing` command group (`settings`, `stats`); `fetch_official_blacklist()` fetches from discord-phishing-links GitHub repo with exponential backoff.
  - `actions.py` — detection pipeline execution: in-memory byte caching of attachments before message deletion, DB logging with content and attachments, user recovery DM, punishment execution (`timeout`/`kick`/`ban`/`warn`), and moderator alerts with message previews, embed summaries, and re-uploaded attachment evidence. `PhishingAlertView` provides interactive action buttons (False Positive, Ban, Timeout, Unban).
  - `commands.py` — `/antiphishing settings` (interactive UI dashboard `SettingsDashboardView` with dropdown selects for action, timeout duration, alert channels, mod roles, bypass role, and modal for custom DM) and `/antiphishing stats` (detection breakdown).
  - `domain.py` — URL extraction from text, embed fields/titles/descriptions/footers/authors, and attachment descriptions. Domain normalization, official blacklist fetching, custom blocklist matching, and typosquatting regex scanning.
  - `rate_limit.py` — in-memory tracker detecting multi-channel link spreading (3+ unique channels with links in 10s); hourly auto-pruning task cleans stale entries.

## Intents

Default + `members=True` + `message_content=True` (required for anti-phishing). Server Members Intent + Message Content Intent must be enabled in Discord Dev Portal.

## Testing quirks

- `libsql_client.create_client` is the only network mock (`conftest.py:mock_db` autouse). All `db.py` function bodies execute for real.
- `conftest.py:clean_globals` autouse fixture resets `domain.official`, `rate_limit._tracker`, and `db._client` between tests.
- `mock_db` fixture also sets `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` env vars so `db.get_db()` doesn't raise.
- `src/main.py` is never imported in tests — fresh `commands.Bot` instances are created via `simcord_bot` fixture, with anti-phishing + channel-clear registered.
- `simcord.assert_error` is required after slash commands that trigger `app_commands.checks` to mark expected errors as inspected.
- Pytest `network` marker (`@pytest.mark.network`) flags tests requiring live external network access (e.g. GitHub blacklist fetches). Run `pytest -m "not network"` for fast offline testing.

## Gotchas

- `render.yaml` deploys as free web service on Render; healthcheck at `/health` is mandatory.
- File-based logs on Render are ephemeral. Use Render logs for live monitoring.
- `.env` is real credentials — never commit or expose.

## Commit Guidelines

All commits must follow the **Conventional Commits** specification to ensure a semantic, clean, and detailed project history.

### Message Format
```
<type>(<scope>): <subject>

[optional body]

[optional footer(s)]
```

- **Subject**: Write in the present tense, imperative mood (e.g., "add", not "added" or "adds"). Limit the subject line to 75 characters and do not end it with a period.
- **Body**: Use bullet points in the body to explain the *what* and *why* of the change (motivation, context, and impact), rather than the *how*. Keep line lengths under 72 characters.
- **Breaking Changes**: Indicate breaking changes by placing an `!` after the type/scope, or by adding `BREAKING CHANGE:` at the beginning of a footer.

### Commit Types
- `feat` — A new feature or slash command.
- `fix` — A bug fix.
- `docs` — Documentation changes (e.g., editing `AGENTS.md` or code docstrings).
- `style` — Code style, formatting, semicolon fixes (no logic changes).
- `refactor` — Code changes that neither fix a bug nor add a feature.
- `perf` — Code changes that improve performance.
- `test` — Adding, updating, or correcting tests (e.g., pytest/SimCord).
- `chore` — Maintenance, configuration, and dependencies.
- `ci` / `build` — CI/CD workflows, build scripts, or deployment config (e.g., `render.yaml`).

### Examples
- **Simple**: `docs: add conventional commits guidelines to AGENTS.md`
- **With Scope**: `feat(anti_phishing): add rate-limit heuristic for spam links`
- **Detailed**:
  ```git
  feat(groq): introduce configurable Groq system prompt

  - Allows guild admins to customize the personality and prompt instructions for the /ask Groq command.
  - Defaults to the standard anime-girl personality if not specified in the guild settings.

  Resolves #42
  ```

