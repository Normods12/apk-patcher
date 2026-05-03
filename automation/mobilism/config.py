import os
from pathlib import Path

# Base directory for this module
MODULE_DIR = Path(__file__).resolve().parent

# Where to store the standalone DB
DB_PATH = MODULE_DIR / "mobilism_apps.db"

# The Mobilism Android Releases forum URL
MOBILISM_URL = "https://forum.mobilism.me/viewforum.php?f=399"

# Pages to scrape in one run
PAGES_TO_SCRAPE = 3

# Dashboard settings
DASHBOARD_PORT = 8092
DASHBOARD_HOST = "0.0.0.0"

# User Agent for scraping
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Request timeout
REQUEST_TIMEOUT = 20
