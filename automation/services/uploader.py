import requests
import json
import logging
import os
from pathlib import Path
from automation.config import REQUEST_TIMEOUT_SECONDS

class FileUploader:
    @staticmethod
    def upload_file(file_path: Path) -> str:
        """
        Uploads a file to GoFile.io and returns the download page URL.
        Returns None if upload fails.
        """
        try:
            # 1. Get best server
            # GoFile API v1/servers returns {status: "ok", data: {servers: [{name: "store1", ...}]}}
            logging.debug("Getting GoFile server...")
            response = requests.get("https://api.gofile.io/servers", timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "ok":
                logging.error(f"GoFile API Error (getServer): {data}")
                return None

            if "data" in data and "servers" in data["data"] and len(data["data"]["servers"]) > 0:
                 server = data["data"]["servers"][0]["name"]
            else:
                 # Fallback/Old API structure just in case
                 server = data.get("data", {}).get("server")

            if not server:
                logging.error("Could not determine GoFile server.")
                return None

            # 2. Upload file
            upload_url = f"https://{server}.gofile.io/uploadFile"
            logging.info(f"Uploading {file_path.name} to {upload_url}...")
            
            with open(file_path, "rb") as f:
                response = requests.post(
                    upload_url, 
                    files={"file": f},
                    timeout=600  # 10 minute timeout for large files
                )
                response.raise_for_status()
                
            upload_data = response.json()
            if upload_data.get("status") == "ok":
                download_link = upload_data["data"]["downloadPage"]
                logging.info(f"Upload successful: {download_link}")
                return download_link
            else:
                logging.error(f"GoFile Upload Failed: {upload_data}")
                return None

        except Exception as e:
            logging.exception(f"FileUploader Exception: {e}")
            return None

    @staticmethod
    def upload_to_catbox(file_path: Path) -> str:
        """
        Uploads a file to Catbox.moe and returns a DIRECT download link.
        Perfect for GitHub Actions to download from.
        """
        try:
            logging.info(f"[*] Uploading {file_path.name} to Catbox...")
            url = "https://catbox.moe/user/api.php"
            with open(file_path, "rb") as f:
                payload = {
                    "reqtype": "fileupload",
                    "userhash": "" # Leave empty for anonymous
                }
                files = {"fileToUpload": f}
                response = requests.post(url, data=payload, files=files, timeout=600)
                response.raise_for_status()
                
            link = response.text.strip()
            if link.startswith("https://"):
                logging.info(f"[OK] Catbox Upload successful: {link}")
                return link
            else:
                logging.error(f"[!] Catbox Error: {link}")
                return None
        except Exception as e:
            logging.exception(f"Catbox Upload Exception: {e}")
            return None
