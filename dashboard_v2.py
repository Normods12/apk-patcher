import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add current directory to sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Load .env
load_dotenv(BASE_DIR / ".env")

import replace_last_dex
from automation.services.uploader import FileUploader

app = FastAPI(title="APK Patching Dashboard")

# Directories
INPUT_DIR = BASE_DIR / "Input-apk"
OUTPUT_DIR = BASE_DIR / "Output-apk"
DEX_DIR = BASE_DIR / "Dex-to-add"
LOG_DIR = BASE_DIR / "logs"
LOCKS_DIR = BASE_DIR / "locks"

for _path in (INPUT_DIR, OUTPUT_DIR, DEX_DIR, LOG_DIR, LOCKS_DIR):
    try:
        _path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Warning: Could not create directory {_path}: {e}")

# State
class Job(BaseModel):
    id: str
    filename: str
    status: str = "Pending"
    logs: List[str] = []
    progress: int = 0
    download_url: Optional[str] = None
    created_at: str = ""

jobs = {}

# WebSocket connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

# Logging capture
class WebSocketHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        # We'll use a globally accessible queue or direct broadcast if possible
        # Since this is synchronous, we run it in a loop
        asyncio.create_task(manager.broadcast({"type": "log", "content": log_entry}))

logger = logging.getLogger("dashboard")
logger.setLevel(logging.DEBUG)
ws_handler = WebSocketHandler()
ws_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(ws_handler)
logger.addHandler(logging.StreamHandler())

# Helper to run commands and capture output
async def run_logged_command(cmd, job_id=None):
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        text = line.decode().strip()
        if text:
            logger.info(text)
            if job_id and job_id in jobs:
                jobs[job_id].logs.append(text)
                await manager.broadcast({"type": "job_update", "job": jobs[job_id].dict()})
    
    await process.wait()
    return process.returncode

async def process_apk_task(job_id: str, file_path: Path):
    job = jobs[job_id]
    try:
        job.status = "Processing"
        job.progress = 10
        await manager.broadcast({"type": "job_update", "job": job.dict()})

        # 1. Resolve DEX
        logger.info(f"[*] Starting job {job_id} for {file_path.name}")
        dex_candidates = sorted(DEX_DIR.glob("classes*.dex"))
        if not dex_candidates:
            logger.error("No payload DEX found in Dex-to-add folder!")
            job.status = "Failed"
            await manager.broadcast({"type": "job_update", "job": job.dict()})
            return

        payload_dex = dex_candidates[0]
        job.progress = 30
        await manager.broadcast({"type": "job_update", "job": job.dict()})

        # 2. Patch
        logger.info(f"[*] Patching {file_path.name} with {payload_dex.name}...")
        output_path = OUTPUT_DIR / file_path.name
        
        # We'll call the logic directly but wrap prints in logger
        # To simplify, we'll just use the run function from replace_last_dex
        # and capture its prints if we could, but better to call the components
        
        target_dex = replace_last_dex.replace_last_dex(file_path, payload_dex, output_path)
        logger.info(f"[OK] Replaced {target_dex}")
        
        job.progress = 60
        await manager.broadcast({"type": "job_update", "job": job.dict()})

        # 3. Sign
        signer = Path(r"C:\Users\smadd\Desktop\Cursor\UniversalPatcher\tools\uber-apk-signer.jar")
        if signer.exists():
            logger.info("[*] Signing APK...")
            # Run signer as a subprocess to capture logs
            cmd = ["java", "-jar", str(signer), "-a", str(output_path), "--overwrite"]
            ret = await run_logged_command(cmd, job_id)
            if ret == 0:
                logger.info("[OK] APK Signed successfully.")
            else:
                logger.warning("[!] Signing might have failed or had warnings.")
        else:
            logger.warning("[!] Signer not found, skipping signing step.")

        job.progress = 80
        await manager.broadcast({"type": "job_update", "job": job.dict()})

        # 4. Upload
        logger.info("[*] Uploading to GoFile...")
        loop = asyncio.get_event_loop()
        download_link = await loop.run_in_executor(None, FileUploader.upload_file, output_path)
        if download_link:
            logger.info(f"[OK] Upload successful: {download_link}")
            job.download_url = download_link
        else:
            logger.error("[!] Upload failed.")

        job.status = "Completed"
        job.progress = 100
        await manager.broadcast({"type": "job_update", "job": job.dict()})

        # --- Send to Telegram even for Local jobs ---
        if download_link:
            await send_telegram_direct(f"✅ <b>Local Patch Success!</b>\n\n📦 <b>File:</b> {file_path.name}\n📥 <a href='{download_link}'>Download from GoFile</a>")

    except Exception as e:
        logger.exception(f"Error processing job {job_id}: {e}")
        job.status = "Failed"
        await manager.broadcast({"type": "job_update", "job": job.dict()})

@app.get("/", response_class=HTMLResponse)
async def get_index():
    template_path = BASE_DIR / "templates" / "index.html"
    return template_path.read_text(encoding="utf-8")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.post("/upload")
async def upload_apk(file: UploadFile = File(...), mode: str = Form("local")):
    job_id = str(uuid.uuid4())[:8]
    file_path = INPUT_DIR / file.filename
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    job = Job(
        id=job_id,
        filename=file.filename,
        created_at=datetime.now().strftime("%H:%M:%S"),
        status="Uploading to Cloud" if mode == "github" else "Pending"
    )
    jobs[job_id] = job
    
    # Start task in background
    if mode == "github":
        asyncio.create_task(auto_cloud_task(job_id, file_path))
    else:
        asyncio.create_task(process_apk_task(job_id, file_path))
    
    return {"job_id": job_id}

async def auto_cloud_task(job_id: str, file_path: Path):
    job = jobs[job_id]
    try:
        # 1. Upload to Catbox (Direct Link) first to get a link for GitHub
        logger.info(f"[*] AUTO-CLOUD: Uploading {file_path.name} to Catbox for GitHub...")
        loop = asyncio.get_event_loop()
        temp_link = await loop.run_in_executor(None, FileUploader.upload_to_catbox, file_path)
        
        if not temp_link:
            logger.error("[!] Failed to get temporary link for GitHub.")
            job.status = "Failed"
            await manager.broadcast({"type": "job_update", "job": job.dict()})
            return

        # 2. Trigger GitHub Action
        logger.info(f"[OK] Temporary link: {temp_link}. Triggering GitHub...")
        job.status = "GitHub Triggered"
        job.progress = 50
        await manager.broadcast({"type": "job_update", "job": job.dict()})
        
        # Call the existing trigger logic
        await trigger_github_internal(temp_link, job_id)
        
        job.progress = 100
        job.status = "Sent to Cloud"
        await manager.broadcast({"type": "job_update", "job": job.dict()})

    except Exception as e:
        logger.error(f"Auto-cloud error: {e}")
        job.status = "Failed"
        await manager.broadcast({"type": "job_update", "job": job.dict()})

async def trigger_github_internal(url: str, job_id: str = None):
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPO")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    bot_token = os.getenv("TELEGRAM_TOKEN")
    
    if token and repo:
        try:
            import requests
            gh_url = f"https://api.github.com/repos/{repo}/dispatches"
            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json"
            }
            payload = {
                "event_type": "patch_apk",
                "client_payload": {
                    "url": url,
                    "telegram_chat_id": chat_id,
                    "telegram_token": bot_token
                }
            }
            resp = requests.post(gh_url, json=payload, headers=headers)
            if resp.status_code == 204:
                logger.info("[OK] GitHub Action triggered successfully.")
                return True
            else:
                logger.error(f"[!] GitHub API Error: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"[!] Failed to trigger GitHub: {e}")
    else:
        logger.warning("[!] GITHUB_TOKEN or GITHUB_REPO not set. Action not triggered.")
    return False

@app.post("/trigger-github")
async def trigger_github_endpoint(url: str = Form(...)):
    job_id = f"GH-{str(uuid.uuid4())[:5]}"
    job = Job(id=job_id, filename="Remote APK", created_at=datetime.now().strftime("%H:%M:%S"))
    jobs[job_id] = job
    await trigger_github_internal(url, job_id)
    return {"job_id": job_id}

async def send_telegram_direct(text: str):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        try:
            import requests
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        except:
            pass

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
