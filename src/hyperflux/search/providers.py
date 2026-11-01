"""Fetch raw search results from DDGS, Bing RSS, or DuckDuckGo HTML (in that order)."""

import xml.etree.ElementTree as ET
from html.parser import HTMLParser

import requests

from hyperflux.search.text import clean_search_text, normalize_result_url

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None


class _DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._field = None
        self._text = []
        self._href = ""

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        classes = (dict(attrs).get("class") or "").split()
        if "result__a" in classes:
            self._field = "title"
            self._text = []
            self._href = dict(attrs).get("href") or ""
        elif "result__snippet" in classes:
            self._field = "body"
            self._text = []

    def handle_data(self, data):
        if self._field:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._field:
            text = " ".join("".join(self._text).split())
            if text:
                if self._field == "title":
                    self.results.append({
                        "title": text,
                        "body": "",
                        "url": self._href,
                    })
                elif self.results and not self.results[-1]["body"]:
                    self.results[-1]["body"] = text
            self._field = None
            self._text = []


def _search_ddgs(query, max_results):
    if DDGS is None:
        return []
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []


def _search_bing_rss(query, max_results):
    response = requests.get(
        "https://www.bing.com/search",
        params={
            "q": query,
            "format": "rss",
            "setlang": "en-US",
            "cc": "us",
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    results = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        body = (item.findtext("description") or "").strip()
        url = (item.findtext("link") or "").strip()
        if title or body:
            results.append({"title": title, "body": body, "url": url})
        if len(results) >= max_results:
            break
    return results


def _search_duckduckgo_html(query):
    response = requests.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    response.raise_for_status()
    parser = _DuckDuckGoHTMLParser()
    parser.feed(response.text)
    return parser.results


def fetch_search_results(query: str, max_results=3):
    """Return up to max_results {title, body, url} dicts; raise RuntimeError if all providers fail."""
    query = query.strip()
    max_results = max(1, min(int(max_results), 8))
    if not query:
        return []

    fetch_errors = []
    results = _search_ddgs(query, max_results)

    if not results:
        try:
            results = _search_bing_rss(query, max_results)
        except (requests.exceptions.RequestException, ET.ParseError) as error:
            fetch_errors.append(f"Bing search unavailable: {error}")

    if not results:
        try:
            results = _search_duckduckgo_html(query)
        except requests.exceptions.RequestException as error:
            fetch_errors.append(f"DuckDuckGo search unavailable: {error}")

    if not results and fetch_errors:
        raise RuntimeError(fetch_errors[0])

    normalized = []
    for result in results:
        if not isinstance(result, dict):
            continue
        title = clean_search_text(str(result.get("title") or ""))
        body = clean_search_text(str(result.get("body") or ""))
        url = normalize_result_url(
            str(result.get("url") or result.get("href") or result.get("link") or "")
        )
        if title or body:
            normalized.append({
                "title": title or "Untitled result",
                "body": body,
                "url": url,
            })
        if len(normalized) >= max_results:
            break
    return normalized
