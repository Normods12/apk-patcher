import os
import logging
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

INPUT_DIR = BASE_DIR / "input_files"
OUTPUT_DIR = BASE_DIR / "output_files"
LOG_DIR = BASE_DIR / "logs"
LOCKS_DIR = BASE_DIR / "locks"
_raw_db_path = os.getenv("DB_PATH", str(BASE_DIR / "apps.db"))
_db_path_candidate = Path(_raw_db_path)
if _db_path_candidate.is_absolute():
    DB_PATH = _db_path_candidate
else:
    # Resolve relative DB paths from project root for stable behavior across launch contexts.
    DB_PATH = (BASE_DIR.parent / _db_path_candidate).resolve()

TARGET_URL = "https://modded-1.com/"
TARGET_APPS_BASE_URL = "https://modded-1.com/apps"
GAMEDVA_BASE_URL = "https://gamedva.com/"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT_SECONDS = 20

MONITOR_LOG_FILE = LOG_DIR / "monitor.log"
WORKER_LOG_FILE = LOG_DIR / "worker.log"

MONITOR_PAGES_TO_SCAN = int(os.getenv("MONITOR_PAGES_TO_SCAN", "3"))
WORKER_POLL_INTERVAL_SECONDS = 30
WORKER_BATCH_LIMIT = int(os.getenv("WORKER_BATCH_LIMIT", "10"))
WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "2"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_MAX_DOCUMENT_MB = int(os.getenv("TELEGRAM_MAX_DOCUMENT_MB", "1999"))
LARGE_FILE_THRESHOLD_MB = int(os.getenv("LARGE_FILE_THRESHOLD_MB", "50"))

# Generic CLI patcher command. If it contains "{input_file}", that placeholder is replaced.
# If it does not contain the placeholder, "<input_file>" is appended automatically.
PATCHER_COMMAND = os.getenv("PATCHER_COMMAND", "python patcher.py")

# Optional dedicated integration for your UniversalPatcher repo (fast_patcher.py flow).
UNIVERSAL_PATCHER_DIR = os.getenv("UNIVERSAL_PATCHER_DIR", "")

# Downloader acceleration (safe fallback enabled by default).
USE_ARIA2C = os.getenv("USE_ARIA2C", "1").strip() not in {"0", "false", "False"}
ARIA2C_PATH = os.getenv("ARIA2C_PATH", "aria2c")
ARIA2C_MAX_CONNECTIONS = int(os.getenv("ARIA2C_MAX_CONNECTIONS", "16"))
ARIA2C_TIMEOUT_SECONDS = int(os.getenv("ARIA2C_TIMEOUT_SECONDS", "300"))
_aria2_candidates_raw = os.getenv("ARIA2C_CONNECTION_CANDIDATES", "").strip()
if _aria2_candidates_raw:
    ARIA2C_CONNECTION_CANDIDATES = [
        int(token.strip())
        for token in _aria2_candidates_raw.split(",")
        if token.strip().isdigit() and int(token.strip()) > 0
    ]
else:
    ARIA2C_CONNECTION_CANDIDATES = [ARIA2C_MAX_CONNECTIONS]
DOWNLOAD_HARD_TIMEOUT_SECONDS = int(os.getenv("DOWNLOAD_HARD_TIMEOUT_SECONDS", "300"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

for _path in (INPUT_DIR, OUTPUT_DIR, LOG_DIR, LOCKS_DIR):
    try:
        _path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Warning: Could not create directory {_path}: {e}")
