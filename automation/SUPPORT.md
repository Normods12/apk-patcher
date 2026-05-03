# UniPatch — Support & Context

Purpose
- Single-file project summary intended to provide an autonomous agent or human operator quick, actionable context for running, debugging, and integrating this automation system.

Architecture (high level)
- Monitor: scrapes target site pages for app name + version and queues new updates into SQLite.
- Database: `automation/apps.db` (configurable via `DB_PATH`) stores rows with dedupe on (app_name, version).
- Worker: polls DB, downloads APKs, runs patcher (either `PATCHER_COMMAND` or `UNIVERSAL_PATCHER_DIR` fast_patcher flow), stores outputs, and notifies via Telegram.
- Services: modular helpers in `automation/services/` (downloader, scraper, processor, telegram_notifier, gamedva_checker, runtime_control).
- Dashboard: lightweight HTTP status server `automation/scripts/status_server.py` showing DB snapshot and logs, with control actions.

Primary dataflow / workflow
- 1) `monitor` scrapes pages -> constructs `AppRecord(app_name, version, download_url)`.
- 2) For each candidate: run GameDVA check (`gamedva_has_version`); if not present, insert into DB.
- 3) `worker` fetches unprocessed rows, downloads the APK (aria2c preferred, Python fallback), writes to `input_files/`.
- 4) `processor` runs either `PATCHER_COMMAND` or `UNIVERSAL_PATCHER_DIR` (`fast_patcher.py`) with a file-lock to avoid concurrent patcher runs.
- 5) Processed APKs copied to `output_files/`; `worker` marks rows processed/failed and sends Telegram messages/documents if configured.

Key files
- Entrypoint: [automation/main.py](automation/main.py)
- Config: [automation/config.py](automation/config.py)
- Monitor: [automation/monitor/monitor.py](automation/monitor/monitor.py)
- Worker: [automation/worker/worker.py](automation/worker/worker.py)
- DB helpers: [automation/database/db.py](automation/database/db.py)
- Services: [automation/services](automation/services) (downloader.py, scraper.py, processor.py, telegram_notifier.py, gamedva_checker.py, runtime_control.py)
- Dashboard: [automation/scripts/status_server.py](automation/scripts/status_server.py)
- Utility: [automation/scripts/enqueue_from_scraper.py](automation/scripts/enqueue_from_scraper.py)

Important configuration & environment variables
- `DB_PATH` : path to SQLite DB (default `automation/apps.db`).
- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` : enable Telegram uploads/notifications.
- `PATCHER_COMMAND` : shell command to run the patcher; supports `{input_file}` placeholder.
- `UNIVERSAL_PATCHER_DIR` : when set, worker uses `py fast_patcher.py` flow in that directory.
- `USE_ARIA2C`, `ARIA2C_PATH`, `ARIA2C_MAX_CONNECTIONS`, `ARIA2C_TIMEOUT_SECONDS` : downloader tuning.
- `WORKER_CONCURRENCY`, `WORKER_BATCH_LIMIT`, `WORKER_POLL_INTERVAL_SECONDS`, `MONITOR_PAGES_TO_SCAN`
- `DOWNLOAD_HARD_TIMEOUT_SECONDS` : global hard timeout for downloads.

Run & dev commands
- Create venv and install:
  - `python -m venv .venv` then activate and `pip install -r automation/requirements.txt`
- Run monitor once:
  - `python -m automation.monitor.monitor` (or `python -m automation.monitor.monitor --pages N` by env var)
- Run worker loop:
  - `python -m automation.worker.worker` or use `automation/scripts/start_worker_bg.bat` on Windows.
- Start dashboard:
  - `python automation/scripts/status_server.py` (defaults to `127.0.0.1:8090` or set `DASHBOARD_PORT`)

Debugging and common issues
- No new DB rows: monitor may skip because `gamedva_has_version` returned true; to force queue for testing use `automation/scripts/enqueue_from_scraper.py` which bypasses GameDVA.
- `no such table: apps`: run `automation.database.db.init_db()` or restart monitor/worker; backup DB if needed before reset.
- Patcher failures (`fast_patcher.py completed but no output APK`): check `UNIVERSAL_PATCHER_DIR` logs, ensure patcher dependencies are available and `fast_patcher.py` produces output in its `output_apks/` directory; examine `automation/input_files/` and `automation/output_files/`.
- Download timeouts / aria2c errors: check network connectivity, `ARIA2C_PATH`, and increase `DOWNLOAD_HARD_TIMEOUT_SECONDS` or `ARIA2C_TIMEOUT_SECONDS`.
- Telegram 413 or upload failures: respect `TELEGRAM_MAX_DOCUMENT_MB` or upload externally and send link.

Operational notes
- Runtime control: `automation/services/runtime_control.py` maintains `runtime/control.json` used by dashboard actions (`force_stop`, `resume`) to pause/resume worker activity safely.
- Logs: `automation/logs/monitor.log` and `automation/logs/worker.log` are primary places to inspect for failures.
- Backups: when resetting DB, move existing DB to `automation/` with timestamp (the project uses the pattern `apps_fresh_YYYYMMDD_HHMMSS.db.backup_...`).

Agent integration guidance
- Provide these items as context to another agent for full control:
  - absolute `DB_PATH`, `BASE_DIR`, `UNIVERSAL_PATCHER_DIR` (if set)
  - `runtime/control.json` contents (current stop/paused state)
  - tail of `automation/logs/worker.log` and `monitor.log`
  - sample rows from DB (`SELECT * FROM apps LIMIT 10`)
  - `PATCHER_COMMAND` value and whether `fast_patcher.py` is available
- Recommended agent actions: run `init_db()` if needed, run monitor to queue, then run worker while watching dashboard; report failures and suggest config changes.

Where outputs land
- Downloaded inputs: `automation/input_files/`
- Processed APKs: `automation/output_files/`
- DB: `automation/apps.db` (or `DB_PATH`)

Suggested next steps
- If you want a minimal, repeatable test: set `UNIVERSAL_PATCHER_DIR` to an accessible patcher or set `PATCHER_COMMAND` to a stub that copies input->output, then enqueue a small set and watch worker process.

Contact
- File created by automation assistant; update this file if you add integrations or change workflows.
