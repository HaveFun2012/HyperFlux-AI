"""Combine, de-duplicate, rank, and compact search results for the local model."""

import re
from concurrent.futures import ThreadPoolExecutor

from hyperflux.config import Config
from hyperflux.search.providers import fetch_search_results
from hyperflux.search.text import (
    clean_search_text,
    is_trusted_search_domain,
    normalize_result_url,
    search_query_variants,
)

_STOP_WORDS = {
    "about", "after", "also", "and", "are", "can", "could", "did",
    "does", "for", "from", "have", "into", "last", "me", "more",
    "please", "that", "the", "their", "there", "these", "they",
    "this", "those", "was", "what", "when", "where", "which", "who",
    "why", "with", "would", "you",
}


def _words(text):
    return {word.casefold() for word in re.findall(r"\b[\w'-]+\b", text)}


def rank_search_results(query: str, results, max_chars: int | None = None) -> str:
    """Rank result snippets by query-term coverage and fit them to a text budget."""
    query_terms = {
        word.casefold()
        for word in re.findall(r"\b[\w'-]+\b", query)
        if len(word) > 2 and word.casefold() not in _STOP_WORDS
    }
    ranked_results = []
    for index, result in enumerate(results):
        title = clean_search_text(str(result.get("title") or ""))
        body = clean_search_text(str(result.get("body") or ""))
        score = 2 * len(query_terms & _words(title)) + len(query_terms & _words(body))
        url = normalize_result_url(str(result.get("url") or ""))
        if is_trusted_search_domain(url):
            score *= 1.5
        ranked_results.append((
            score,
            index,
            {"title": title or "Untitled result", "body": body, "url": url},
        ))
    ranked_results.sort(key=lambda item: (-item[0], item[1]))

    budget = max_chars or Config.SEARCH_CONTEXT_MAX_CHARS
    context = "LIVE WEB SEARCH RESULTS:\n"
    for _, _, result in ranked_results:
        remaining = budget - len(context)
        if remaining <= 0:
            break
        source_url = result["url"]
        source = f"\n  Source: {source_url}" if source_url else ""
        entry = (
            f"- Title: {result['title']}{source}\n"
            f"  Snippet: {result['body']}\n"
        )
        if len(entry) > remaining:
            entry = entry[:remaining].rstrip()
        if entry:
            context += entry
    return context


def search_web(query: str, max_results=3, fetch=fetch_search_results) -> str:
    """Search the query plus its variants; return ranked context or a 'SEARCH ERROR:' string."""
    results = []
    fetch_errors = []
    try:
        results.extend(fetch(query, max_results))
    except RuntimeError as error:
        fetch_errors.append(str(error))

    variants = search_query_variants(query)
    with ThreadPoolExecutor(max_workers=Config.SEARCH_MAX_VARIANTS) as executor:
        futures = [executor.submit(fetch, variant, max_results) for variant in variants]
        for future in futures:
            try:
                results.extend(future.result())
            except RuntimeError as error:
                fetch_errors.append(str(error))

    unique_results = []
    seen_results = set()
    for result in results:
        key = result.get("url", "").casefold() or result.get("title", "").casefold()
        if key and key not in seen_results:
            seen_results.add(key)
            unique_results.append(result)
    if not unique_results:
        if fetch_errors:
            return f"SEARCH ERROR: {fetch_errors[0]}"
        return "SEARCH ERROR: No recent search results found."
    return rank_search_results(query, unique_results)
