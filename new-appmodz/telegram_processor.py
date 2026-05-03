#!/usr/bin/env python3
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# Add project root to sys.path to allow imports from automation
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load local .env if it exists
LOCAL_ENV = BASE_DIR / ".env"
if LOCAL_ENV.exists():
    load_dotenv(LOCAL_ENV)

# Get config from environment (which now includes local .env)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

from automation.services.telegram_notifier import TelegramNotifier
from automation.services.uploader import FileUploader
import replace_last_dex

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("telegram_workflow")

STATE_FILE = BASE_DIR / "telegram_state.json"

class TelegramWorkflow:
    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.chat_id = str(TELEGRAM_CHAT_ID)
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.notifier = TelegramNotifier(token=self.token, chat_id=self.chat_id)
        self.state = self._load_state()

    def _load_state(self):
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text())
            except:
                pass
        return {"last_update_id": 0}

    def _save_state(self):
        STATE_FILE.write_text(json.dumps(self.state, indent=2))

    def fetch_new_apks(self):
        """Fetch updates from Telegram and identify new APK files or download links."""
        offset = self.state.get("last_update_id", 0) + 1
        url = f"{self.base_url}/getUpdates?offset={offset}&timeout=30"
        
        try:
            response = requests.get(url, timeout=40)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error(f"Failed to fetch updates: {e}")
            return []

        if not data.get("ok"):
            logger.error(f"Telegram API error: {data}")
            return []

        updates = data.get("result", [])
        items_to_process = []

        import re
        # Pattern to find URLs
        URL_PATTERN = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')
        # Pattern to find filename in message text (e.g. "📂 Fɪʟᴇ ɴᴀᴍᴇ : CCleaner_v26.06.0_MOD.apk")
        # Supports different fonts and labels
        FILENAME_PATTERN = re.compile(r'(?:Fɪʟᴇ ɴᴀᴍᴇ|File Name|Name)\s*[:\-]\s*([\w\._\s-]+?\.apk)', re.IGNORECASE | re.UNICODE)

        for update in updates:
            self.state["last_update_id"] = max(self.state["last_update_id"], update["update_id"])
            
            message = update.get("message") or update.get("channel_post")
            if not message:
                continue

            # Check if it's from the correct chat
            if str(message.get("chat", {}).get("id")) != self.chat_id:
                continue

            # 1. Check for direct document (APK)
            document = message.get("document")
            if document and document.get("file_name", "").lower().endswith(".apk"):
                items_to_process.append({
                    "type": "document",
                    "file_id": document["file_id"],
                    "file_name": document["file_name"],
                    "message_id": message["message_id"]
                })
                continue

            # 2. Check for URLs in message text
            text = message.get("text", "") or message.get("caption", "")
            urls = URL_PATTERN.findall(text)
            if urls:
                logger.debug(f"Found URLs in message: {urls}")
                logger.debug(f"Message text: {text!r}")
                
                # Try to find any word ending in .apk
                file_name = "downloaded_app.apk"
                
                # First try the specific label pattern
                fn_match = FILENAME_PATTERN.search(text)
                if fn_match:
                    file_name = fn_match.group(1).strip()
                    logger.debug(f"Regex match (label): {file_name}")
                else:
                    # Fallback: Find the first string that ends with .apk
                    all_apks = re.findall(r'([\w\._\s-]+\.apk)', text, re.IGNORECASE)
                    if all_apks:
                        file_name = all_apks[0].strip()
                        logger.debug(f"Regex match (fallback): {file_name}")
                        if len(file_name) < 5:
                            file_name = "downloaded_app.apk"
                    else:
                        logger.debug("No .apk matches found in text.")

                # Cleanup filename
                file_name = "".join(c for c in file_name if c.isalnum() or c in "._- ").strip()
                if not file_name.lower().endswith(".apk"):
                    file_name += ".apk"
                
                logger.info(f"Detected filename: {file_name}")

                download_url = urls[0]

                items_to_process.append({
                    "type": "url",
                    "url": download_url,
                    "file_name": file_name,
                    "message_id": message["message_id"]
                })

        self._save_state()
        return items_to_process

    def download_telegram_file(self, file_id, output_path):
        """Download a file from Telegram servers (limit 20MB)."""
        try:
            file_info_url = f"{self.base_url}/getFile?file_id={file_id}"
            resp = requests.get(file_info_url, timeout=20)
            resp.raise_for_status()
            file_path = resp.json()["result"]["file_path"]

            download_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
            return self.download_url_file(download_url, output_path)
        except Exception as e:
            logger.error(f"Failed to download telegram file {file_id}: {e}")
            return False

    def download_url_file(self, url, output_path):
        """Download a file from a generic URL."""
        try:
            logger.info(f"Downloading from {url} to {output_path.name}...")
            # Use a browser-like user agent to avoid being blocked
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            with requests.get(url, stream=True, timeout=600, headers=headers) as r:
                r.raise_for_status()
                # Check content type if possible
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192*4):
                        f.write(chunk)
            return True
        except Exception as e:
            logger.error(f"Failed to download URL {url}: {e}")
            return False

    def process_and_upload(self, item_info):
        """Download, process, and upload a single APK."""
        input_dir = BASE_DIR / "Input-apk"
        output_dir = BASE_DIR / "Output-apk"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        local_input = input_dir / item_info["file_name"]
        
        # 1. Download
        success = False
        if item_info["type"] == "document":
            success = self.download_telegram_file(item_info["file_id"], local_input)
        elif item_info["type"] == "url":
            success = self.download_url_file(item_info["url"], local_input)

        if not success:
            return

        # 2. Process (Patch & Sign)
        logger.info(f"Processing {item_info['file_name']}...")
        try:
            # Re-resolve paths like replace_last_dex.py does
            dex_dir, _, _ = replace_last_dex.resolve_default_paths(BASE_DIR)
            dex_candidates = sorted(dex_dir.glob("classes*.dex"))
            payload_dex = dex_candidates[0] if dex_candidates else None
            
            if not payload_dex:
                logger.error("No payload DEX found in Dex-to-add")
                return

            # Signer path fallback
            signer = Path(r"C:\Users\smadd\Desktop\Cursor\UniversalPatcher\tools\uber-apk-signer.jar")
            
            # Run the replacement
            replace_last_dex.run(payload_dex, input_dir, output_dir, signer if signer.exists() else None)
            
            # 3. Upload back
            processed_apk = output_dir / item_info["file_name"]
            if processed_apk.exists():
                logger.info(f"Uploading processed {item_info['file_name']} back to Telegram...")
                caption = f"✅ Processed & Signed: {item_info['file_name']}"
                
                # Attempt Telegram upload
                if self.notifier.send_document(processed_apk, caption):
                    logger.info(f"Successfully processed and uploaded {item_info['file_name']} to Telegram")
                else:
                    # Fallback to GoFile
                    logger.warning(f"Telegram upload failed for {item_info['file_name']}. Trying GoFile fallback...")
                    self.notifier.send_message(f"⏳ File is large or Telegram upload failed. Uploading {item_info['file_name']} to GoFile...")
                    
                    download_link = FileUploader.upload_file(processed_apk)
                    if download_link:
                        msg = f"✅ Processed & Signed: {item_info['file_name']}\n\n📥 Download Link (GoFile):\n{download_link}"
                        self.notifier.send_message(msg)
                        logger.info(f"Successfully uploaded {item_info['file_name']} to GoFile: {download_link}")
                    else:
                        logger.error(f"GoFile fallback also failed for {item_info['file_name']}")
                        self.notifier.send_message(f"❌ Failed to upload {item_info['file_name']} to both Telegram and GoFile.")
            else:
                logger.error(f"Processed APK not found: {processed_apk}")

        except Exception as e:
            logger.exception(f"Error during processing of {item_info['file_name']}: {e}")
        finally:
            # Clean up local files if needed (optional)
            # local_input.unlink(missing_ok=True)
            pass

    def run(self):
        logger.info("Starting Telegram workflow...")
        apks = self.fetch_new_apks()
        
        if not apks:
            logger.info("No new APKs found.")
            return

        logger.info(f"Found {len(apks)} new APK(s) to process.")
        for apk in apks:
            self.process_and_upload(apk)
        
        logger.info("Workflow completed.")

if __name__ == "__main__":
    workflow = TelegramWorkflow()
    workflow.run()
