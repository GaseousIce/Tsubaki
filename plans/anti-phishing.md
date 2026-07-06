# Anti-Phishing Feature Plan

## Branch
`feat/anti-phishing`

## Overview
Detect phishing links in Discord messages via two methods:
1. **Domain blacklist** — 22k+ domains from `nikolaischunk/discord-phishing-links` (cached, auto-updated)
2. **Rate-limit heuristic** — user sends links across 3+ channels in 10s → suspicious

On detection: delete message → DM recovery instructions → punish → alert moderators.

---

## Files

### Create: `src/anti_phishing.py`

#### Domain sourcing
- Fetch `domain-list.json` from GitHub raw on startup
- Cache to `data/domain_cache.json` (re-fetch if >24h stale)
- Falls back to hardcoded set (~20 common patterns) if fetch fails
- After blacklist check, also scan domains for substring patterns (`discord-nitro`, `steam-gift`, `dlscord`, etc.) to catch typosquats

#### Detection pipeline (`on_message` listener)

```python
def is_phishing(message) -> tuple[bool, str]:
    # reason = "blacklist" | "rate_limit" | None
    domains = extract_domains(message.content + all embed fields)
    if any(domain in blacklist or match_pattern(domain) for domain in domains):
        return (True, "blacklist")
    if rate_limit_check(message.author, message.channel.id, message.content):
        return (True, "rate_limit")
    return (False, None)
```

#### Rate-limit tracker
- In-memory `dict[int, list[tuple[channel_id, timestamp, content]]]`
- Prune entries older than `ANTI_PHISHING_RATE_WINDOW` (default 10s)
- Trigger if 3+ unique channels OR same content in 2+ channels within window

#### Action flow
1. Delete message
2. DM user with recovery embed (password reset, 2FA, revoke apps, reset token, Discord support)
3. Punish:
   - `timeout` — duration parsed from `7d`, `2w`, `14d`, `28d` (max 28d clamp)
   - `kick` — remove from server
   - `ban` — permanent ban
   - `warn` — no server action
4. Alert: post embed to each channel in guild's `alert_channels` list
5. Log to file

#### Config persistence
`data/antiphishing_config.json`:
```json
{
  "guild_id": {
    "enabled": true,
    "action": "timeout",
    "timeout_duration": 604800,
    "alert_channels": []
  }
}
```

#### Slash command group: `/antiphishing`
- **Permission gate:** `administrator` (TODO: refine to `moderate_members`/`kick_members`/`ban_members` based on action)
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

### Modify: `src/main.py`

| Change | Detail |
|---|---|
| `intents.message_content = True` | Add after `intents.members = True` |
| `from anti_phishing import setup as setup_anti_phishing` | New import |
| `setup_anti_phishing(bot)` | Call in `setup_hook()` after `setup_channel_clear(bot)` |

### Modify: `.env.example`

```env
ANTI_PHISHING_BYPASS_ROLE_ID=123456789012345678
ANTI_PHISHING_RATE_ENABLED=true
ANTI_PHISHING_RATE_THRESHOLD=3
ANTI_PHISHING_RATE_WINDOW=10
```

### Modify: `render.yaml`

Add `ANTI_PHISHING_BYPASS_ROLE_ID` with `sync: false`.

---

## Dependencies
None — `discord-py` has all needed APIs. Uses stdlib `urllib` / bundled `aiohttp` for fetching the domain list.

---

## Security
- Commands gated behind `administrator` permission
- TODO comment to refine permissions in production
- Bypass role via `ANTI_PHISHING_BYPASS_ROLE_ID` env var — users with this role are skipped entirely
- Never log or expose `DISCORD_TOKEN`
