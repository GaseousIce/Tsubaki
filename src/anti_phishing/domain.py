import asyncio
import logging
import re
from urllib.parse import urlparse

import aiohttp

import db

logger = logging.getLogger("discord")

official: set[str] = set()

_BLACKLIST_URL = (
    "https://raw.githubusercontent.com/nikolaischunk/discord-phishing-links/refs/heads/main/domain-list.json"
)
_SUSPICIOUS_LIST_URL = (
    "https://raw.githubusercontent.com/nikolaischunk/discord-phishing-links/refs/heads/main/suspicious-list.json"
)

_URL_RE = re.compile(r"https?://(?:[-\w.]|(?:/[\w\-./~%!#$&'()*+,;=:?@]))+")


async def _fetch_url(url: str, retries: int, delays: list[int], label: str) -> set[str]:
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
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


async def fetch_blacklist(retries: int = 3) -> set[str]:
    delays = [5, 10, 20]
    official_domains, suspicious_domains = await asyncio.gather(
        _fetch_url(_BLACKLIST_URL, retries, delays, "Blacklist"),
        _fetch_url(_SUSPICIOUS_LIST_URL, retries, delays, "Suspicious list"),
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


def extract_urls(text: str, embeds=None) -> list[str]:
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
        try:
            url_clean = url.strip().rstrip("/")
            if url_clean:
                url_lower = url_clean.lower()
                if url_lower not in seen:
                    seen.add(url_lower)
                    result.append(url_lower)
        except Exception:
            pass
    return result


def _extract_hostnames(urls: list[str]) -> set[str]:
    hostnames: set[str] = set()
    for url in urls:
        try:
            parsed = urlparse(url)
            host = parsed.hostname
            if host:
                hostnames.add(host.lower())
        except Exception:
            pass
    return hostnames


async def find_in_blacklists(urls: list[str]) -> tuple[str | None, str | None]:
    hostnames = _extract_hostnames(urls)

    for hostname in hostnames:
        if hostname in official:
            return (hostname, "official_blacklist")

    for hostname in hostnames:
        try:
            source = await db.get_blocklist_source(hostname)
            if source:
                return (hostname, f"custom_blocklist ({source})")
        except Exception as exc:
            logger.warning("DB blocklist check failed for %s: %s", hostname, exc)

    for url in urls:
        try:
            source = await db.get_blocklist_source(url)
            if source:
                return (url, f"custom_blocklist ({source})")
        except Exception as exc:
            logger.warning("DB blocklist check failed for URL %s: %s", url, exc)

    return (None, None)
