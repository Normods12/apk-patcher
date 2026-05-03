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

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
load_dotenv(BASE_DIR / ".env")

import replace_last_dex
from automation.services.uploader import FileUploader

app = FastAPI(title="APK Patching Dashboard")

# Directories
INPUT_DIR = BASE_DIR / "Input-apk"
OUTPUT_DIR = BASE_DIR / "Output-apk"
DEX_DIR = BASE_DIR / "Dex-to-add"
INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
DEX_DIR.mkdir(exist_ok=True)

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
        download_link = FileUploader.upload_file(output_path)
        if download_link:
            logger.info(f"[OK] Upload successful: {download_link}")
            job.download_url = download_link
        else:
            logger.error("[!] Upload failed.")

        job.status = "Completed"
        job.progress = 100
        await manager.broadcast({"type": "job_update", "job": job.dict()})

    except Exception as e:
        logger.exception(f"Error processing job {job_id}: {e}")
        job.status = "Failed"
        await manager.broadcast({"type": "job_update", "job": job.dict()})

@app.get("/", response_class=HTMLResponse)
async def get_index():
    template_path = BASE_DIR / "templates" / "index.html"
    return template_path.read_text()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.post("/upload")
async def upload_apk(file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())[:8]
    file_path = INPUT_DIR / file.filename
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    job = Job(
        id=job_id,
        filename=file.filename,
        created_at=datetime.now().strftime("%H:%M:%S")
    )
    jobs[job_id] = job
    
    # Start task in background
    asyncio.create_task(process_apk_task(job_id, file_path))
    
    return {"job_id": job_id}

@app.post("/trigger-github")
async def trigger_github(url: str = Form(...)):
    # Placeholder for GitHub Trigger logic
    job_id = f"GH-{str(uuid.uuid4())[:5]}"
    logger.info(f"[*] Triggering GitHub Action for: {url}")
    
    job = Job(
        id=job_id,
        filename="Remote APK",
        status="GitHub Triggered",
        created_at=datetime.now().strftime("%H:%M:%S")
    )
    jobs[job_id] = job
    
    # Actually trigger GitHub via API if Token is present
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPO")
    
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
                "client_payload": {"url": url}
            }
            resp = requests.post(gh_url, json=payload, headers=headers)
            if resp.status_code == 204:
                logger.info("[OK] GitHub Action triggered successfully.")
            else:
                logger.error(f"[!] GitHub API Error: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"[!] Failed to trigger GitHub: {e}")
    else:
        logger.warning("[!] GITHUB_TOKEN or GITHUB_REPO not set in .env. Action not triggered.")

    return {"job_id": job_id}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
