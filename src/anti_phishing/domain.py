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

_BLACKLIST_URL = (
    "https://raw.githubusercontent.com/nikolaischunk/discord-phishing-links/refs/heads/main/domain-list.json"
)
_SUSPICIOUS_LIST_URL = (
    "https://raw.githubusercontent.com/nikolaischunk/discord-phishing-links/refs/heads/main/suspicious-list.json"
)

_URL_RE = re.compile(r"https?://[^\s<>\"'()]+")


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


def extract_urls(
    text: str | None,
    embeds: Sequence[Any] | None = None,
    attachments: Sequence[Any] | None = None,
) -> list[str]:
    raw = list(_URL_RE.findall(text or ""))

    if embeds:
        for embed in embeds:
            if getattr(embed, "url", None):
                raw.append(embed.url)
            if getattr(embed, "description", None):
                raw.extend(_URL_RE.findall(embed.description))
            if getattr(embed, "title", None):
                raw.extend(_URL_RE.findall(embed.title))
            for field in getattr(embed, "fields", []):
                if getattr(field, "name", None):
                    raw.extend(_URL_RE.findall(field.name))
                if getattr(field, "value", None):
                    raw.extend(_URL_RE.findall(field.value))
            footer = getattr(embed, "footer", None)
            if footer and getattr(footer, "text", None):
                raw.extend(_URL_RE.findall(footer.text))
            author = getattr(embed, "author", None)
            if author and getattr(author, "url", None):
                raw.append(author.url)

    if attachments:
        for attachment in attachments:
            desc = getattr(attachment, "description", None)
            if desc:
                raw.extend(_URL_RE.findall(desc))

    seen: set[str] = set()
    result: list[str] = []
    for url in raw:
        try:
            url_clean = url.strip().rstrip("/.,;!?:")
            if url_clean:
                url_lower = url_clean.lower()
                if url_lower not in seen:
                    seen.add(url_lower)
                    result.append(url_lower)
        except AttributeError:
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


def _domain_candidates(hostname: str) -> list[str]:
    """Return all domain suffix candidates for subdomain matching (e.g. sub.evil.com -> [sub.evil.com, evil.com])."""
    parts = hostname.split(".")
    return [".".join(parts[i:]) for i in range(len(parts) - 1)]


async def find_in_blacklists(
    urls: list[str],
    check_custom_blocklist: bool = True,
) -> tuple[str | None, str | None]:
    hostnames = _extract_hostnames(urls)

    for hostname in hostnames:
        for candidate in _domain_candidates(hostname):
            if candidate in official:
                return (hostname, "official_blacklist")

    if not check_custom_blocklist:
        return (None, None)

    for hostname in hostnames:
        for candidate in _domain_candidates(hostname):
            try:
                source = await db.get_blocklist_source(candidate)
                if source:
                    return (hostname, f"custom_blocklist ({source})")
            except Exception as exc:
                logger.warning("DB blocklist check failed for %s: %s", candidate, exc)

    for url in urls:
        try:
            source = await db.get_blocklist_source(url)
            if source:
                return (url, f"custom_blocklist ({source})")
        except Exception as exc:
            logger.warning("DB blocklist check failed for URL %s: %s", url, exc)

    return (None, None)
