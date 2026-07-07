# Anti-Phishing Feature Plan

> **Prerequisite:** this feature introduces `config.toml` — committed app-level config (not secrets).
> Secrets (`DISCORD_TOKEN`, `GROQ_API_KEY`, `TURSO_*`) remain in `.env`.
>
> **Important:** `config.toml` must **not** be in `.gitignore`. It is committed to the repo.

---

## `config.toml` (new file)

Committed to repo, holds non-secret settings with comments. Create at project root:

```toml
[anti_phishing]
# Enable rate-limit heuristic (links across 3+ channels in 10s).
rate_enabled = true
# Unique channels before rate-limit triggers.
rate_threshold = 3
# Time window in seconds for rate-limit tracking.
rate_window = 10
# Max fetch attempts for domain blacklist (5s, 10s, 20s backoff).
fetch_retries = 3
```

Per-guild overrides (action, alert channels, mod roles, etc.) use the database layer — see [`plans/per-guild-db.md`](per-guild-db.md).

### `Config` class

New file `src/config.py`:

```python
import tomllib
from dataclasses import dataclass, field

@dataclass
class AntiPhishingConfig:
    rate_enabled: bool = True
    rate_threshold: int = 3
    rate_window: int = 10
    fetch_retries: int = 3

@dataclass
class AppConfig:
    anti_phishing: AntiPhishingConfig = field(default_factory=AntiPhishingConfig)

    @classmethod
    def load(cls, path: str = "config.toml") -> "AppConfig":
        with open(path, "rb") as f:
            data = tomllib.load(f)
        ap = data.get("anti_phishing", {})
        return cls(anti_phishing=AntiPhishingConfig(**ap))
```

Loaded once in `main.py`. Passed to `setup_anti_phishing(bot, config)`.

### Files affected by config layer

| File | Change |
|---|---|
| `config.toml` | Create with `[anti_phishing]` section above |
| `src/config.py` | Create `AppConfig` with `load()` |
| `src/anti_phishing/domain.py` | Read `fetch_retries` from `config` param |
| `src/anti_phishing/rate_limit.py` | Read `rate_window`, `rate_threshold`, `rate_enabled` from `config` |
| `src/main.py` | Load `AppConfig`, pass to `setup_anti_phishing()` |

---

## Overview
Detect phishing links in Discord messages via two methods:
1. **Domain blacklist** — 22k+ domains from `nikolaischunk/discord-phishing-links` (fetched on startup from `https://raw.githubusercontent.com/nikolaischunk/discord-phishing-links/main/domain-list.json`)
2. **Rate-limit heuristic** — user sends links across 3+ channels in 10s → suspicious

On detection: delete message → DM recovery instructions → punish → alert moderators.

---

## Files

### Create: `src/anti_phishing/` package

```
src/anti_phishing/
  __init__.py       # setup(), on_message listener
  domain.py         # fetching + matching
  rate_limit.py     # rate-limit heuristic
  actions.py        # punish logic, DM embed
  commands.py       # /antiphishing command group
  config.py         # per-guild config read/write
```

#### Domain sourcing (`domain.py`)
- Fetch `domain-list.json` from `https://raw.githubusercontent.com/nikolaischunk/discord-phishing-links/main/domain-list.json` on startup with retry: 5s → 10s → 20s
- Default max 3 attempts, configurable via `[anti_phishing].fetch_retries` in `config.toml`
- Store fetched domain set in a module-level `official: set[str]` (populated during `setup()`, accessed by `find_in_blacklists()`).
- If all retries fail:
  - Skip official blacklist checks (rate-limit heuristic still runs)
  - Custom blocklist in DB still works (survives fetch failure)
  - Post alert embed to each `alert_channels` pinging all `mod_roles`
- After official blacklist check, also check `custom_blocklist` in DB (auto-added zero-day findings)
- Finally, scan domains against `typosquat_patterns` from DB — a pattern matches if it appears as a whole segment between `.`/`-` boundaries (regex: `(?<=^|[.\-])<pattern>(?=$|[.\-])`). If matched and domain not in either blocklist, auto-add to `custom_blocklist` with source `"typosquat"`

#### Domain matching helpers (`domain.py`)

- `extract_domains(text: str, embeds: list[discord.Embed] | None = None) -> list[str]` — extract URLs via `https?://(?:[-\w.]|/[\w\-./~%!#$&'()*+,;=:?@])+`, return deduplicated domain-only (scheme/path stripped) list. If `embeds` provided, collect `embed.url` (discard if same host as the message itself, typically `discord.com/channels/...`) and `embed.description`, run the same regex extraction, combine with text-extracted domains.
- `find_in_blacklists(domains: list[str]) -> tuple[str | None, str | None]` — returns `(domain, "blacklist")` if domain found in the module-level `official` set, or `(domain, "custom")` if found via `is_in_blocklist()` in the DB. Returns `(None, None)` if not in either.
- `match_typosquat(domains: list[str]) -> tuple[str | None, str | None]` — fetch patterns via `get_patterns()`, check each domain against each pattern with word-boundary regex `(?<=^|[.\-])<escaped_pattern>(?=$|[.\-])`, return `(domain, matched_pattern)` on first hit.

#### Detection pipeline (`__init__.py` — `on_message` listener)

**Listener registration:** in `setup(bot, config)`, call `bot.add_listener(on_message)` (not a slash command or cog). The `on_message` listener checks `bypass_role` from the per-guild DB config before entering the pipeline.

Check order: official blacklist → custom blocklist (DB) → pattern scan → rate-limit.

When a pattern scan catches a domain not in either blocklist, call `add_to_blocklist(domain, "typosquat")` to auto-cache it. After any detection, call `log_detection(guild_id, domain, reason)` for stats.

```python
async def is_phishing(message) -> tuple[str | None, str | None]:
    # reason = "blacklist" | "custom" | "pattern" | "rate_limit" | None
    domains = extract_domains(message.content, message.embeds)  # embed.url + embed.description only
    domain, reason = find_in_blacklists(domains)  # official + custom
    if domain:
        return (domain, reason)
    domain, pattern = match_typosquat(domains)  # scan against DB patterns
    if domain:
        await add_to_blocklist(domain, "typosquat")
        return (domain, "pattern")
    if rate_limit_check(message.author.id, message.channel.id, message.content):
        return (domain, "rate_limit")
    return (None, None)
```

#### Rate-limit tracker (`rate_limit.py`)
- In-memory `dict[int, list[tuple[int, float, str]]]` — keyed by user_id, value is list of `(channel_id, timestamp, content)` tuples. Timestamp is `time.time()`.
- `rate_limit_check(user_id: int, channel_id: int, content: str) -> bool` — returns True if rate-limit triggered.
- Prune entries older than `[anti_phishing].rate_window` (default 10s) using `time.time() - entry_timestamp > rate_window`.
- Trigger if 3+ unique channels OR same content in 2+ channels within window

#### Action flow (`actions.py`)
1. Log detection to DB via `log_detection(guild_id, domain, reason)`
2. Delete message
3. DM user with recovery embed:
   - Default embed (used when `dm_message` is `null`):
     ```python
     embed = discord.Embed(
         title="Security Alert",
         description="You may have interacted with a phishing link. Take these steps immediately:",
         color=discord.Color.red(),
     )
     embed.add_field(name="1. Reset Your Password", value="https://discord.com/settings/account", inline=False)
     embed.add_field(name="2. Enable Two-Factor Authentication", value="https://discord.com/settings/account", inline=False)
     embed.add_field(name="3. Revoke Authorized Apps", value="Settings > Authorized Apps", inline=False)
     embed.add_field(name="4. Reset Your Discord Token", value="Settings > Advanced > Regenerate Token", inline=False)
     embed.add_field(name="5. Contact Discord Support", value="https://support.discord.com/hc/en-us", inline=False)
     embed.set_footer(text="If you didn't click anything, you can ignore this message.")
     ```
   - If `dm_message` is set to a custom string, use that string as the embed `description` in place of the default. Keep all fields and footer identical. If `dm_message` is `None` or empty string, use the default embed.
   - DM send is best-effort: catch `discord.Forbidden` (user has DMs closed) and log, continue to punish/alert.
4. Punish (all punish actions catch `discord.Forbidden` and log it):
   - `timeout` — parse duration string (`7d`, `2w`, `14d`, `28d`), clamp to 28 days max, apply via `await member.timeout(discord.utils.utcnow() + datetime.timedelta(seconds=seconds), reason=...)`. Max 28 days (2419200s) enforced server-side but clamp defensively.
   - `kick` — `await member.kick(reason=...)`
   - `ban` — `await member.ban(reason=...)`
   - `warn` — no server action (DM only)
5. Alert: post embed to each channel in guild's `alert_channels` list, pinging all `mod_roles`
6. Log to file

#### Config persistence (`config.py`)
Uses the shared database layer — see [`plans/per-guild-db.md`](per-guild-db.md).

Default config shape (merged with what's in DB):
```json
{
  "enabled": true,
  "action": "timeout",
  "timeout_duration": 604800,
  "alert_channels": [],
  "mod_roles": [],
  "dm_message": null,
  "bypass_role": 0
}
```

#### Slash command group (`commands.py`): `/antiphishing`
- **Permission gate:** `@app_commands.default_permissions(administrator=True)` on the command group (mod roles are ping targets only, not permission gates). Using `default_permissions` means Discord enforces the check automatically — no manual check needed in the command body.
- **Commands:**

| Command | Signature | Description |
|---|---|---|
| `action` | `action: str` (choices: timeout/kick/ban/warn) | Set punishment |
| `timeout` | `duration: str` | Set timeout (e.g. `7d`, `2w`, `14d`) |
| `alert add` | `channel: TextChannel` | Add alert channel |
| `alert remove` | `channel: TextChannel` | Remove alert channel |
| `alert list` | — | List alert channels |
| `enable` | — | Enable for this guild |
| `disable` | — | Disable for this guild |
| `status` | — | Show current config |
| `stats` | — | Total detections, top blocked domains, last detection timestamp |
| `dm-message` | `text: str` (optional) | Set custom DM recovery message; omit to reset to default |
| `mod-role add` | `role: Role` | Add role to alert ping list |
| `mod-role remove` | `role: Role` | Remove role from alert ping list |
| `mod-role list` | — | List mod roles |
| `bypass-role set` | `role: Role` | Set role that bypasses all phishing checks |
| `bypass-role remove` | — | Remove bypass role |
| `bypass-role list` | — | Show current bypass role |
| `patterns add` | `text: str` | Add typosquat pattern (e.g. `discord-nitro`) |
| `patterns remove` | `text: str` | Remove typosquat pattern |
| `patterns list` | — | List all typosquat patterns |

### Modify: `src/main.py`

| Change | Detail |
|---|---|
| `intents.message_content = True` | Add after `intents.members = True` |
| `from config import AppConfig` | New import |
| `from db import migrate` | New import |
| `from anti_phishing import setup as setup_anti_phishing` | New import |
| `config = AppConfig.load()` | After `load_dotenv()`, before bot startup |
| `await migrate()` | First `await` in `setup_hook()` (DB must exist before any feature uses it) |

Resulting `setup_hook()` flow (annotated with existing code):

```python
async def setup_hook():
    global ai_service
    await migrate()                              # NEW — DB first

    try:
        ai_service = GroqAskService()            # existing
        logger.info("Groq /ask service initialized")
    except ValueError:
        ai_service = None
        logger.warning("GROQ_API_KEY missing: /ask command is disabled")

    setup_channel_clear(bot)                     # existing

    setup_anti_phishing(bot, config)             # NEW

    synced = await bot.tree.sync()               # existing
    logger.info("Synced %s slash command(s)", len(synced))
```

> **Important:** `message_content` is a **privileged intent**. It must be enabled in the Discord Developer Portal under **Bot > Privileged Gateway Intents > MESSAGE CONTENT INTENT**. If not toggled on, `on_message` will receive empty content for most messages.

### Modify: `.env.example`

Add Turso credentials (secrets, not committed):

```env
TURSO_DATABASE_URL=libsql://your-db.turso.io
TURSO_AUTH_TOKEN=your-token
```

No `ANTI_PHISHING_*` vars — all app-level anti-phishing settings live in `config.toml`.

---

## TODO

### DB layer (prerequisite — [`plans/per-guild-db.md`](per-guild-db.md))

- [ ] Add `libsql-client` to `pyproject.toml`
- [ ] Create `src/db.py` — client, guild config, detection log, custom blocklist, typosquat patterns, migration
- [ ] Add `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` to `.env.example`
- [ ] Call `migrate()` from `main.py` on startup
- [ ] Create Turso database on turso.tech, configure locally + Render dashboard

### Config layer

- [ ] Create `config.toml` with `[anti_phishing]` section
- [ ] Create `src/config.py` — `AppConfig` dataclass with `load()`

### Anti-phishing package (`src/anti_phishing/`)

- [ ] **`config.py`** — per-guild config read/write via `src.db`
- [ ] **`domain.py`** — fetch blacklist with retry, check official + custom blocklists, typosquat pattern scan with auto-add
- [ ] **`rate_limit.py`** — in-memory tracker, 3+ channels or same content in 2+ channels within `rate_window`
- [ ] **`__init__.py`** — `setup(bot, config)`, `on_message` listener, detection pipeline orchestrator
- [ ] **`actions.py`** — log detection to DB, delete, DM, punish, alert mod_roles, log to file
- [ ] **`commands.py`** — full `/antiphishing` group with `administrator` gate

### Integration

- [ ] **`src/main.py`** — add `message_content` intent, import `AppConfig`, load config, pass to `setup_anti_phishing(bot, config)`
- [ ] **`.env.example`** — add `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`
- [ ] **`render.yaml`** — add `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` to `envVars` (both `sync: false`)
- [ ] **`.gitignore`** — verify `config.toml` is **not** listed (it is a committed file)
- [ ] **Run `ruff check + format`** on `src/`

## Security
- Commands gated behind `@app_commands.default_permissions(administrator=True)` — Discord enforces server-side
- Bypass role checked from per-guild DB config — users with this role are skipped at the listener level (message not processed)
- Each DB call is wrapped in try/except in the caller (on_message / command body) — a Turso outage logs but doesn't crash the event loop

