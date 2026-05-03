import re
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup

from automation.config import GAMEDVA_BASE_URL, REQUEST_TIMEOUT_SECONDS, USER_AGENT


VERSION_RE = re.compile(r"\bv?(\d+(?:[.\-]\d+)*(?:[a-zA-Z0-9]*)?)\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _tokenize_name(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) > 1}


def _extract_versions(text: str) -> set[str]:
    return {m.lower().lstrip("v") for m in VERSION_RE.findall(text)}


def gamedva_has_version(app_name: str, version: str) -> tuple[bool, str]:
    query = urllib.parse.quote_plus(app_name)
    url = f"{GAMEDVA_BASE_URL}?s={query}"

    last_error: Exception | None = None
    response = None
    for wait_seconds in (0, 1, 2):
        if wait_seconds:
            time.sleep(wait_seconds)
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                timeout=(10, REQUEST_TIMEOUT_SECONDS),
            )
            response.raise_for_status()
            break
        except Exception as exc:
            last_error = exc

    if response is None:
        raise RuntimeError(f"GameDVA lookup failed for '{app_name}': {last_error}")

    soup = BeautifulSoup(response.text, "html.parser")
    wanted_version = version.lower().lstrip("v")
    wanted_tokens = _tokenize_name(app_name)

    articles = soup.select("article")
    if not articles:
        return False, "no_search_results"

    matching_articles = []
    for article in articles:
        title_node = article.select_one("h1, h2, h3, .entry-title")
        title = _normalize(title_node.get_text(" ", strip=True) if title_node else "")
        title_tokens = _tokenize_name(title)

        # Keep only plausibly same app results.
        if wanted_tokens and title_tokens and len(wanted_tokens.intersection(title_tokens)) == 0:
            continue

        matching_articles.append(article)

    if not matching_articles:
        return False, "no_matching_app_title"

    for article in matching_articles:
        text = article.get_text(" ", strip=True)
        versions = _extract_versions(text)
        if wanted_version in versions:
            return True, "exact_version_found"

    return False, "exact_version_not_found"
