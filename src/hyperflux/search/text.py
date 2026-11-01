"""Pure text helpers for search queries, result URLs, and snippets."""

import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse, urlunparse

from hyperflux.config import Config


def optimize_search_query(user_input: str) -> str:
    """Turn a chat message into a compact search-engine query."""
    query = user_input.strip()
    query = re.sub(
        r"^(?:(?:search|look)\s+(?:the\s+)?(?:web|internet)\s+(?:for|about)|"
        r"search:|web:|/search|look\s+up|find\s+(?:info(?:rmation)?\s+)?on)\s*",
        "",
        query,
        flags=re.IGNORECASE,
    )
    has_news_intent = bool(re.search(r"\b(?:news|story|stories|article|articles)\b", query, re.IGNORECASE))
    query = re.sub(
        r"^(?:the\s+)?(?:latest|most recent)\s+(?:news\s+)?"
        r"(?:story|stories|article|articles)\s+(?:about|on)\s+",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\b(?:can you|could you|please|tell me about|check the|look up|"
        r"search the web for|search the internet for)\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )
    current_month = datetime.now().astimezone().strftime("%B %Y")
    query = re.sub(r"\bthis month\b", current_month, query, flags=re.IGNORECASE)
    query = re.sub(r"\s+", " ", query)
    query = query.strip(" \t\r\n?!.")
    if has_news_intent and not re.search(r"\bnews\b", query, re.IGNORECASE):
        query = f"{query} news"
    return query


def search_query_variants(query: str) -> list[str]:
    """Extra phrasings of a query, searched alongside the original."""
    variants = []
    release_query = re.sub(r"\bupdates?\b", "releases", query, flags=re.IGNORECASE)
    release_query = re.sub(r"\bnews\b", "announcements", release_query, flags=re.IGNORECASE)
    if release_query.casefold() != query.casefold():
        variants.append(release_query)

    focused_query = re.sub(
        r"\b(?:latest|news|announcements|this|month|today|recent)\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )
    focused_query = re.sub(r"\s+", " ", focused_query).strip()
    if focused_query and focused_query.casefold() != query.casefold():
        variants.append(f"{focused_query} releases")
    return list(dict.fromkeys(variants))[:Config.SEARCH_MAX_VARIANTS]


def clean_search_text(text: str) -> str:
    boilerplate_patterns = (
        r"javascript is disabled",
        r"cookie policy",
        r"terms of service",
        r"click here to",
        r"all rights reserved",
        r"official site",
    )
    for pattern in boilerplate_patterns:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def normalize_result_url(url: str) -> str:
    """Unwrap DuckDuckGo redirects and drop query strings and fragments."""
    if not url:
        return ""
    parsed_url = urlparse(url)
    if parsed_url.hostname and parsed_url.hostname.casefold().endswith("duckduckgo.com"):
        target = parse_qs(parsed_url.query).get("uddg", [""])[0]
        if target:
            url = target
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
        return ""
    return urlunparse(parsed_url._replace(query="", fragment=""))


def is_trusted_search_domain(url: str) -> bool:
    hostname = urlparse(url).hostname
    if not hostname:
        return False
    hostname = hostname.casefold().rstrip(".")
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in Config.TRUSTED_SEARCH_DOMAINS
    )
