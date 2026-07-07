import asyncio
import logging
import re

import aiohttp

import db

logger = logging.getLogger("discord")

# Official blacklist — populated during setup().
official: set[str] = set()

_BLACKLIST_URL = "https://raw.githubusercontent.com/nikolaischunk/discord-phishing-links/main/domain-list.json"

_URL_RE = re.compile(r"https?://(?:[-\w.]|(?:/[\w\-./~%!#$&'()*+,;=:?@]))+")


async def fetch_blacklist(retries: int = 3) -> set[str]:
    """
    Fetch the official phishing domain list with exponential backoff.
    Returns a set of domains, or an empty set if all attempts fail.
    """
    delays = [5, 10, 20]
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(_BLACKLIST_URL, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
                    # data is either a list of domains or {"domains": [...]}
                    if isinstance(data, list):
                        return set(data)
                    return set(data.get("domains", []))
        except Exception as exc:
            logger.warning("Blacklist fetch attempt %d/%d failed: %s", attempt + 1, retries, exc)
            if attempt < retries - 1:
                await asyncio.sleep(delays[attempt])
    return set()


def extract_domains(text: str, embeds=None) -> list[str]:
    """
    Extract unique domains from message text and optional embed URLs/descriptions.
    Returns a deduplicated list of bare hostnames (no scheme/path).
    """
    raw = list(_URL_RE.findall(text or ""))

    if embeds:
        for embed in embeds:
            if embed.url:
                raw.append(embed.url)
            if embed.description:
                raw.extend(_URL_RE.findall(embed.description))

    seen: set[str] = set()
    result: list[str] = []
    for url in raw:
        # Strip scheme and path — keep only host.
        host = re.sub(r"^https?://", "", url).split("/")[0].split("?")[0].lower()
        # Remove port if present.
        host = host.split(":")[0]
        if host and host not in seen:
            seen.add(host)
            result.append(host)
    return result


async def find_in_blacklists(domains: list[str]) -> tuple[str | None, str | None]:
    """
    Check domains against the official set and the DB custom blocklist.
    Returns (domain, source) where source is "blacklist" or "custom", or (None, None).
    """
    for domain in domains:
        if domain in official:
            return (domain, "blacklist")
    for domain in domains:
        try:
            if await db.is_in_blocklist(domain):
                return (domain, "custom")
        except Exception as exc:
            logger.warning("DB blocklist check failed for %s: %s", domain, exc)
    return (None, None)


async def match_typosquat(domains: list[str]) -> tuple[str | None, str | None]:
    """
    Check domains against typosquat patterns stored in DB.
    Pattern matched as a whole word segment between . / - boundaries.
    Returns (domain, matched_pattern) or (None, None).
    """
    try:
        patterns = await db.get_patterns()
    except Exception as exc:
        logger.warning("DB pattern fetch failed: %s", exc)
        return (None, None)

    for domain in domains:
        for pattern in patterns:
            escaped = re.escape(pattern)
            if re.search(rf"(?:^|[.\-]){escaped}(?:$|[.\-])", domain):
                return (domain, pattern)
    return (None, None)
