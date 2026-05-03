# Python Automation System

Production-ready automation for monitoring new app versions and processing them.

## Features
- Scrapes `https://modded-1.com/` for app/version/download URL.
- Uses SQLite with dedupe on `(app_name, version)`.
- New records are queued by `processed = 0`.
- Worker downloads input files, runs `python patcher.py <input_file>`, stores output in `output_files/`, and marks records processed.
- Telegram success/failure notifications and processed file upload.
- Rotating logs for monitor and worker.

## Project Structure

```
automation/
├── monitor/
│   └── monitor.py
├── worker/
│   └── worker.py
├── database/
│   └── db.py
├── services/
│   ├── scraper.py
│   ├── downloader.py
│   ├── processor.py
│   └── telegram_notifier.py
├── input_files/
├── output_files/
├── config.py
├── requirements.txt
└── main.py
```

## Local Run (Windows/Linux)

1. Create virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\\Scripts\\activate   # Windows PowerShell
pip install -r automation/requirements.txt
```

2. Set environment variables:

```bash
export TELEGRAM_TOKEN="<your_bot_token>"
export TELEGRAM_CHAT_ID="<your_chat_id>"
# Optional:
# export PATCHER_COMMAND="python patcher.py"
```

3. Run monitor once:

```bash
python -m automation.monitor.monitor
```

4. Run worker loop:

```bash
python -m automation.worker.worker
```

## Cron (monitor every 5 min)

If code is at `/opt/interview-automation`:

```cron
*/5 * * * * cd /opt/interview-automation && /opt/interview-automation/.venv/bin/python -m automation.monitor.monitor >> /opt/interview-automation/automation/logs/cron_monitor.log 2>&1
```

## Ubuntu VPS Setup Guide (when you buy VPS)

1. Buy Ubuntu 22.04/24.04 VPS from provider (Hetzner, DigitalOcean, Linode, Vultr).
2. SSH into server:

```bash
ssh ubuntu@YOUR_SERVER_IP
```

3. Install system packages:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
```

4. Deploy code:

```bash
sudo mkdir -p /opt/interview-automation
sudo chown -R $USER:$USER /opt/interview-automation
git clone <your_repo_url> /opt/interview-automation
cd /opt/interview-automation
```

5. Prepare venv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r automation/requirements.txt
```

6. Verify manually:

```bash
export TELEGRAM_TOKEN="<your_bot_token>"
export TELEGRAM_CHAT_ID="<your_chat_id>"
python -m automation.monitor.monitor
python -m automation.worker.worker
```

7. Install worker systemd service:

```bash
sudo cp automation/deploy/worker.service /etc/systemd/system/interview-worker.service
sudo systemctl daemon-reload
sudo systemctl enable interview-worker.service
sudo systemctl start interview-worker.service
sudo systemctl status interview-worker.service
```

8. Add cron for monitor:

```bash
crontab -e
```

Add:

```cron
*/5 * * * * cd /opt/interview-automation && /opt/interview-automation/.venv/bin/python -m automation.monitor.monitor >> /opt/interview-automation/automation/logs/cron_monitor.log 2>&1
```

## Notes
- Keep `patcher.py` in `/opt/interview-automation` or set `PATCHER_COMMAND`.
- SQLite database file will be created at `automation/apps.db`.
- Logs are in `automation/logs/`.

Exact minimal cron format requested:

```cron
*/5 * * * * python monitor.py
```

## UniversalPatcher Integration (your zip)

If you want the worker to use your attached `UniversalPatcher` project directly, set:

```bash
export UNIVERSAL_PATCHER_DIR="/opt/UniversalPatcher"
```

On Windows PowerShell:

```powershell
$env:UNIVERSAL_PATCHER_DIR = "C:\Users\smadd\Desktop\Cursor\UniversalPatcher"
```

When this env var is set, worker processing will:
1. Copy the downloaded APK into `<UNIVERSAL_PATCHER_DIR>/input_apks/`
2. Run `py fast_patcher.py`
3. Copy newest output APK from `<UNIVERSAL_PATCHER_DIR>/output_apks/` into `automation/output_files/`

If `UNIVERSAL_PATCHER_DIR` is not set, it falls back to generic `PATCHER_COMMAND` mode.
