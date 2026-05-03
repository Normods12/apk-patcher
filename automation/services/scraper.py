import re
import time
from dataclasses import dataclass
from typing import List, Set
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from automation.config import REQUEST_TIMEOUT_SECONDS, TARGET_APPS_BASE_URL, USER_AGENT


VERSION_RE = re.compile(r"\bv?(\d+(?:[.\-]\d+)*(?:[a-zA-Z0-9]*)?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class AppRecord:
    app_name: str
    version: str
    download_url: str


def _extract_version(meta_text: str) -> str:
    if "?" in meta_text:
        left = meta_text.split("?", 1)[0].strip().lstrip("vV").strip()
        if left:
            return left

    match = VERSION_RE.search(meta_text)
    return match.group(1) if match else ""


def _fetch_page(url: str) -> str:
    last_error: Exception | None = None
    for wait_seconds in (0, 2, 4):
        if wait_seconds:
            time.sleep(wait_seconds)
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                timeout=(10, REQUEST_TIMEOUT_SECONDS),
            )
            response.raise_for_status()
            return response.text
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Failed to fetch page after retries: {url} | error={last_error}")


def scrape_target_apps_pages(pages: int = 3) -> List[AppRecord]:
    records: List[AppRecord] = []
    seen: Set[tuple[str, str]] = set()

    for page_no in range(1, pages + 1):
        page_url = TARGET_APPS_BASE_URL if page_no == 1 else f"{TARGET_APPS_BASE_URL}/page/{page_no}"
        html = _fetch_page(page_url)
        soup = BeautifulSoup(html, "html.parser")

        for article in soup.select("article"):
            link = article.select_one("a.app.clickable[href]") or article.find("a", href=True)
            title = article.select_one(".app-name h2, .app-name h3")
            meta = article.select_one(".app-name .app-meta")

            if not link or not title or not meta:
                continue

            app_name = title.get_text(" ", strip=True)
            version = _extract_version(meta.get_text(" ", strip=True))
            if not app_name or not version:
                continue

            detail_url = urljoin(TARGET_APPS_BASE_URL, link["href"].strip())
            key = (app_name.lower(), version.lower())
            if key in seen:
                continue
            seen.add(key)

            records.append(AppRecord(app_name=app_name, version=version, download_url=detail_url))

    return records
