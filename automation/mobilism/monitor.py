import time
import logging

from automation.mobilism.config import PAGES_TO_SCRAPE
from automation.mobilism.db import init_db, app_exists, insert_app
from automation.mobilism.scraper import scrape_mobilism
from automation.services.gamedva_checker import gamedva_has_version

# Configure logging for this module
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("mobilism_monitor")

def run_monitor():
    logger.info("Starting Mobilism Monitor...")
    init_db()

    try:
        apps = scrape_mobilism(PAGES_TO_SCRAPE)
        logger.info(f"Found {len(apps)} apps on Mobilism (first {PAGES_TO_SCRAPE} pages).")
        
        new_updates = 0
        
        for app in apps:
            # 1. Check if we've already seen this exact version
            if app_exists(app.app_name, app.version):
                logger.debug(f"Skipping known: {app.app_name} v{app.version}")
                continue

            # 2. Check GameDVA
            try:
                exists_on_gamedva, reason = gamedva_has_version(app.app_name, app.version)
                
                if exists_on_gamedva:
                    logger.info(f"Ignored (On GameDVA): {app.app_name} v{app.version}")
                    # Optionally store as IGNORED so we don't check GameDVA again
                    insert_app(app.app_name, app.version, app.title, app.url, status="IGNORED")
                elif reason == "exact_version_not_found":
                    # This is the ONLY case we want: App exists, but this version is new
                    logger.info(f"NEW UPDATE FOUND: {app.app_name} v{app.version}")
                    insert_app(app.app_name, app.version, app.title, app.url, status="NEW")
                    new_updates += 1
                else:
                    # App likely doesn't exist on GameDVA at all (reason="no_search_results" or "no_matching_app_title")
                    logger.info(f"Ignored (App not on GameDVA): {app.app_name} v{app.version} | reason={reason}")
                    insert_app(app.app_name, app.version, app.title, app.url, status="IGNORED")
                    
            except Exception as e:
                logger.error(f"Error checking GameDVA for {app.app_name}: {e}")
                
        logger.info(f"Monitor run complete. Found {new_updates} new updates.")
        
    except Exception as e:
        logger.exception(f"Monitor failed with error: {e}")

if __name__ == "__main__":
    run_monitor()
