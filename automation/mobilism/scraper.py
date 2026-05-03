import re
import time
import cloudscraper
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import List, Optional

from automation.mobilism.config import MOBILISM_URL, USER_AGENT, REQUEST_TIMEOUT

@dataclass
class MobilismApp:
    title: str
    url: str
    app_name: str
    version: str

# Regex to extract Name and Version from titles like "Spotify v8.9.10 [Mod]"
# Tries to capture:
# Group 1: Name (before the version)
# Group 2: Version (starting with v or just digits/dots)
TITLE_RE = re.compile(r"^(.+?)\s+v?(\d+(?:\.\d+)+[a-zA-Z0-9\-]*)", re.IGNORECASE)

def _parse_title(title: str) -> tuple[Optional[str], Optional[str]]:
    # Cleanup tags like [Mod], [Pro], (Premium)
    clean_title = re.sub(r"\[.*?\]|\(.*?\)", "", title).strip()
    
    match = TITLE_RE.search(clean_title)
    if match:
        name = match.group(1).strip()
        version = match.group(2).strip()
        return name, version
    return None, None

# Create a scraper instance
scraper = cloudscraper.create_scraper(browser='chrome')

def scrape_mobilism(pages: int = 3) -> List[MobilismApp]:
    results = []
    
    for i in range(pages):
        # Mobilism pagination: start=0, start=50, start=100 (50 topics per page)
        offset = i * 50
        url = f"{MOBILISM_URL}&start={offset}"
        
        try:
            print(f"Scraping Mobilism page {i+1}...")
            # Use cloudscraper instead of requests
            resp = scraper.get(
                url, 
                timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Select topic titles
            # The class for topic links is typically "topictitle"
            links = soup.select("a.topictitle")
            
            for link in links:
                title = link.get_text(strip=True)
                href = link.get("href")
                
                # Check if it's a valid app thread
                if not href or "viewtopic.php" not in href:
                    continue
                    
                full_url = href if href.startswith("http") else f"https://forum.mobilism.me/{href}"
                
                name, version = _parse_title(title)
                if name and version:
                    results.append(MobilismApp(
                        title=title,
                        url=full_url,
                        app_name=name,
                        version=version
                    ))
                    
            time.sleep(1) # Be polite
            
        except Exception as e:
            print(f"Error scraping page {i+1}: {e}")
            
    return results

if __name__ == "__main__":
    # Quick test
    apps = scrape_mobilism(1)
    for app in apps:
        print(f"Found: {app.app_name} | v{app.version}")
