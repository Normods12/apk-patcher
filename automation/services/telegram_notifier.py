import logging
from pathlib import Path

import requests

from automation.config import TELEGRAM_CHAT_ID, TELEGRAM_MAX_DOCUMENT_MB, TELEGRAM_TOKEN


class TelegramNotifier:
    def __init__(self, token: str = None, chat_id: str = None) -> None:
        self.token = token or TELEGRAM_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.enabled else ""

    def send_message(self, text: str) -> None:
        if not self.enabled:
            logging.debug("TelegramNotifier is disabled.")
            return

        logging.debug(f"Sending message to chat ID: {self.chat_id}")
        response = requests.post(
            f"{self.base_url}/sendMessage",
            data={"chat_id": self.chat_id, "text": text},
            timeout=20,
        )
        response.raise_for_status()

    def send_document(self, file_path: Path, caption: str) -> bool:
        if not self.enabled:
            logging.debug("TelegramNotifier is disabled.")
            return False

        logging.debug(f"Sending document to chat ID: {self.chat_id}")
        size_limit_bytes = TELEGRAM_MAX_DOCUMENT_MB * 1024 * 1024
        if not file_path.exists():
            logging.error(f"File does not exist: {file_path}")
            return False

        if file_path.stat().st_size > size_limit_bytes:
            logging.warning(
                f"File size exceeds limit: {file_path.stat().st_size} bytes > {size_limit_bytes} bytes"
            )
            return False

        try:
            with open(file_path, "rb") as document:
                logging.info(f"Sending document: {file_path}")
                response = requests.post(
                    f"{self.base_url}/sendDocument",
                    data={"chat_id": self.chat_id, "caption": caption},
                    files={"document": document},
                    timeout=600,
                )
            if response.status_code == 413:
                logging.error("File too large to upload (HTTP 413).")
                return False

            response.raise_for_status()
            logging.info("Document sent successfully.")
            return True
        except requests.RequestException as e:
            logging.exception(f"Failed to send document: {e}")
            return False
