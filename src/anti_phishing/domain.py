import asyncio
import logging
import re
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

import aiohttp

import db

logger = logging.getLogger("discord")

official: set[str] = set()
allowed: set[str] = set()

PUBLIC_SUFFIXES: set[str] = {
    # Multi-tenant user project hosting platforms
    "github.io",
    "gitlab.io",
    "pages.dev",
    "vercel.app",
    "herokuapp.com",
    "firebaseapp.com",
    "netlify.app",
    "azurewebsites.net",
    "web.app",
    "onrender.com",
    # Common multi-part ccTLDs
    "co.uk",
    "org.uk",
    "gov.uk",
    "ac.uk",
    "me.uk",
    "com.au",
    "net.au",
    "org.au",
    "edu.au",
    "co.jp",
    "ne.jp",
    "or.jp",
    "com.br",
    "net.br",
    "org.br",
    "co.nz",
    "net.nz",
    "org.nz",
    "co.za",
    "org.za",
    "com.mx",
    "org.mx",
    "co.in",
    "net.in",
    "org.in",
}

_BLACKLIST_URL = (
    "https://raw.githubusercontent.com/nikolaischunk/discord-phishing-links/refs/heads/main/domain-list.json"
)
_SUSPICIOUS_LIST_URL = (
    "https://raw.githubusercontent.com/nikolaischunk/discord-phishing-links/refs/heads/main/suspicious-list.json"
)

# F47 & F05: Case-insensitive URL regex allowing parentheses in query parameters
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# F02 & F03: Homoglyph character folding for confusable Cyrillic/Greek characters
_HOMOGLYPH_MAP = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "і": "i",
        "о": "o",
        "р": "p",
        "с": "c",
        "у": "y",
        "х": "x",
        "А": "a",
        "Е": "e",
        "І": "i",
        "О": "o",
        "Р": "p",
        "С": "c",
        "У": "y",
        "Х": "x",
        "ο": "o",
        "ν": "v",
        "ρ": "p",
        "Ο": "o",
    }
)

# F03: Canonical legitimate target domains exempt from typosquatting flags
LEGITIMATE_TARGET_DOMAINS: dict[str, set[str]] = {
    "discord.com": {
        "discord.com",
        "discord.gg",
        "discordapp.com",
        "discordapp.net",
        "discord.media",
        "discordstatus.com",
        "discord.dev",
        "discord.new",
        "discord.gift",
    },
    "steamcommunity.com": {
        "steamcommunity.com",
        "steampowered.com",
        "valvesoftware.com",
    },
}

# F03: Default typosquatting regex patterns and targets
DEFAULT_TYPOSQUAT_PATTERNS: list[tuple[str, str]] = [
    (r"d[il1|]sc[o0]rd", "discord.com"),
    (r"discrod", "discord.com"),
    (r"discorcl", "discord.com"),
    (r"dlsocrd", "discord.com"),
    (r"discord.*nitro|nitro.*discord", "discord.com"),
    (r"discord.*gift|gift.*discord", "discord.com"),
    (r"discord.*airdrop|airdrop.*discord", "discord.com"),
    (r"discord.*app|app.*discord", "discord.com"),
    (r"discord.*claim|claim.*discord", "discord.com"),
    (r"steam.*communit[yv]", "steamcommunity.com"),
    (r"steam.*comminuty", "steamcommunity.com"),
    (r"steam.*trade", "steamcommunity.com"),
    (r"steam.*gift", "steamcommunity.com"),
    (r"steam.*nitro", "steamcommunity.com"),
]

_COMPILED_TYPOSQUAT_PATTERNS = [
    (re.compile(pattern, re.IGNORECASE), target) for pattern, target in DEFAULT_TYPOSQUAT_PATTERNS
]


def _clean_url(url: str) -> str:
    """Trim surrounding punctuation and strip unbalanced markdown closing parentheses."""
    if not isinstance(url, str):
        return ""
    url = url.strip().rstrip("/.,;!?:")
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1].rstrip("/.,;!?:")
    return url.rstrip("/.,;!?:")


# F14: Persistent ClientSession reuse
async def _fetch_url(
    url: str,
    retries: int,
    delays: list[int],
    label: str,
    session: aiohttp.ClientSession | None = None,
) -> set[str]:
    async def _do_fetch(sess: aiohttp.ClientSession) -> set[str]:
        for attempt in range(retries):
            try:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
                    if isinstance(data, list):
                        return set(data)
                    return set(data.get("domains", []))
            except Exception as exc:
                logger.warning("%s fetch attempt %d/%d failed: %s", label, attempt + 1, retries, exc)
                if attempt < retries - 1:
                    await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
        return set()

    if session is not None:
        return await _do_fetch(session)
    async with aiohttp.ClientSession() as owned_session:
        return await _do_fetch(owned_session)


async def fetch_blacklist(retries: int = 3, session: aiohttp.ClientSession | None = None) -> set[str]:
    delays = [5, 10, 20]
    if session is not None:
        official_domains, suspicious_domains = await asyncio.gather(
            _fetch_url(_BLACKLIST_URL, retries, delays, "Blacklist", session=session),
            _fetch_url(_SUSPICIOUS_LIST_URL, retries, delays, "Suspicious list", session=session),
        )
    else:
        async with aiohttp.ClientSession() as owned_session:
            official_domains, suspicious_domains = await asyncio.gather(
                _fetch_url(_BLACKLIST_URL, retries, delays, "Blacklist", session=owned_session),
                _fetch_url(_SUSPICIOUS_LIST_URL, retries, delays, "Suspicious list", session=owned_session),
            )
    merged = official_domains | suspicious_domains
    if merged:
        logger.info(
            "Fetched %d official + %d suspicious = %d total domains",
            len(official_domains),
            len(suspicious_domains),
            len(merged),
        )
    return merged


def extract_urls(
    text: str | None,
    embeds: Sequence[Any] | None = None,
    attachments: Sequence[Any] | None = None,
) -> list[str]:
    raw = list(_URL_RE.findall(text or ""))

    if embeds:
        for embed in embeds:
            if isinstance(getattr(embed, "url", None), str):
                raw.append(embed.url)
            if isinstance(getattr(embed, "description", None), str):
                raw.extend(_URL_RE.findall(embed.description))
            if isinstance(getattr(embed, "title", None), str):
                raw.extend(_URL_RE.findall(embed.title))
            for field in getattr(embed, "fields", []):
                if isinstance(getattr(field, "name", None), str):
                    raw.extend(_URL_RE.findall(field.name))
                if isinstance(getattr(field, "value", None), str):
                    raw.extend(_URL_RE.findall(field.value))
            footer = getattr(embed, "footer", None)
            if footer and isinstance(getattr(footer, "text", None), str):
                raw.extend(_URL_RE.findall(footer.text))

            # F04: Author name and author URL
            author = getattr(embed, "author", None)
            if author:
                author_url = getattr(author, "url", None)
                if not author_url and isinstance(author, dict):
                    author_url = author.get("url")
                if isinstance(author_url, str):
                    raw.append(author_url)

                author_name = getattr(author, "name", None)
                if not author_name and isinstance(author, dict):
                    author_name = author.get("name")
                if isinstance(author_name, str):
                    raw.extend(_URL_RE.findall(author_name))

            # F04: Media image and thumbnail URLs
            for media_attr in ("image", "thumbnail"):
                media = getattr(embed, media_attr, None)
                if media:
                    media_url = getattr(media, "url", None)
                    if not media_url and isinstance(media, dict):
                        media_url = media.get("url")
                    if isinstance(media_url, str):
                        raw.append(media_url)

    if attachments:
        for attachment in attachments:
            desc = getattr(attachment, "description", None)
            if isinstance(desc, str):
                raw.extend(_URL_RE.findall(desc))

    seen: set[str] = set()
    result: list[str] = []
    for url in raw:
        if not isinstance(url, str):
            continue
        try:
            url_clean = _clean_url(url)
            if url_clean:
                url_lower = url_clean.lower()
                if url_lower not in seen:
                    seen.add(url_lower)
                    result.append(url_lower)
        except (AttributeError, TypeError):
            pass
    return result


def _extract_hostnames(urls: list[str]) -> set[str]:
    hostnames: set[str] = set()
    for url in urls:
        try:
            parsed = urlparse(url)
            host = parsed.hostname
            if host:
                # F01: Strip FQDN trailing dots
                host = host.rstrip(".").lower()
                if host:
                    hostnames.add(host)
                    # F02: IDN / Punycode dual normalization
                    try:
                        puny = host.encode("idna").decode("ascii").lower()
                        if puny:
                            hostnames.add(puny)
                    except (UnicodeError, ValueError):
                        pass
                    try:
                        if "xn--" in host:
                            decoded = host.encode("ascii").decode("idna").lower()
                            if decoded:
                                hostnames.add(decoded)
                    except (UnicodeError, ValueError):
                        pass
        except Exception:
            pass
    return hostnames


def _domain_candidates(hostname: str) -> list[str]:
    """Return all domain suffix candidates for subdomain matching, excluding public suffixes."""
    cleaned = hostname.rstrip(".").lower()
    parts = cleaned.split(".")
    candidates: list[str] = []
    for i in range(len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in PUBLIC_SUFFIXES:
            continue
        candidates.append(suffix)
    return candidates or [cleaned]


async def find_in_blacklists(
    urls: list[str],
    check_custom_blocklist: bool = True,
) -> tuple[str | None, str | None]:
    hostnames = _extract_hostnames(urls)

    for hostname in hostnames:
        candidates = _domain_candidates(hostname)
        if any(c in allowed for c in [hostname] + candidates):
            continue
        for candidate in candidates:
            if candidate in official:
                return (hostname, "official_blacklist")

    if not check_custom_blocklist:
        return (None, None)

    for hostname in hostnames:
        candidates = _domain_candidates(hostname)
        if any(c in allowed for c in [hostname] + candidates):
            continue
        for candidate in candidates:
            try:
                source = await db.get_blocklist_source(candidate)
                if source:
                    return (hostname, f"custom_blocklist ({source})")
            except Exception as exc:
                logger.warning("DB blocklist check failed for %s: %s", candidate, exc)

    for url in urls:
        if url in allowed or url.lower() in allowed:
            continue
        try:
            source = await db.get_blocklist_source(url)
            if source:
                return (url, f"custom_blocklist ({source})")
        except Exception as exc:
            logger.warning("DB blocklist check failed for URL %s: %s", url, exc)

    return (None, None)


# F03: Typosquatting pattern engine
async def check_typosquats(
    urls: list[str],
    check_db: bool = True,
) -> tuple[str | None, str | None]:
    """Check candidate hostnames against typosquatting patterns.

    Returns (detected_hostname, reason) or (None, None).
    """
    patterns = list(_COMPILED_TYPOSQUAT_PATTERNS)

    if check_db:
        try:
            database = await db.get_db()
            rows = await database.execute("SELECT pattern, target_domain FROM typosquat_patterns")
            if rows and rows.rows:
                for row in rows.rows:
                    pat, tgt = row[0], row[1]
                    try:
                        patterns.append((re.compile(pat, re.IGNORECASE), tgt))
                    except re.error:
                        pass
        except Exception as exc:
            logger.debug("Failed to query DB typosquat patterns: %s", exc)

    hostnames = _extract_hostnames(urls)
    for hostname in hostnames:
        candidates = _domain_candidates(hostname)
        if not candidates:
            candidates = [hostname]

        if any(c in allowed for c in [hostname] + candidates):
            continue

        folded_hostname = hostname.translate(_HOMOGLYPH_MAP)

        for regex, target in patterns:
            if regex.search(hostname) or regex.search(folded_hostname):
                legit_set = LEGITIMATE_TARGET_DOMAINS.get(target, set())
                is_legit = any(cand in legit_set for cand in candidates)
                if not is_legit:
                    return (hostname, f"typosquat ({target})")

    return (None, None)


async def populate_default_typosquats() -> int:
    """Populate default typosquat patterns into database table if not already present."""
    inserted = 0
    try:
        database = await db.get_db()
        for pattern, target in DEFAULT_TYPOSQUAT_PATTERNS:
            try:
                await database.execute(
                    "INSERT OR IGNORE INTO typosquat_patterns (pattern, target_domain) VALUES (?, ?)",
                    (pattern, target),
                )
                inserted += 1
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Could not populate default typosquat patterns: %s", exc)
    return inserted
