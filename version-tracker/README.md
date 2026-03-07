# Gamedva Version Watch

This standalone helper checks whether the apps you care about still have matching versions on **gamedva.com**, stores a per-day snapshot, and turns that into an easy HTML report that highlights what changed.

## Layout
- `tracker.py`: main CLI for running a check (with optional HTML source or live fetch).
- `apps.json`: sample list of apps that the tracker knows about. Add more entries as needed.
- `data/`: auto-created daily JSON snapshots (`YYYY-MM-DD.json`).
- `reports/`: auto-created HTML summaries (`report-YYYYMMDD-HHMMSS.html`).
- `scripts/run-tracker.bat`: sample batch file for your manual runs.

## Daily flow
1. Run the tracker manually (you will call the `.bat` that points into `tracker.py` once you have the latest HTML).
2. The script loads the latest versions either by parsing your HTML dump or by fetching the configured `gamedva.com/<slug>` pages.
3. It writes a daily JSON snapshot, compares it to the previous one, and produces a colored HTML report outlining which apps got new versions and which are still pending.
4. You can keep sharing the report to Telegram (or any other channel) however you are currently sharing the HTML from the existing pipeline.

## Running
```powershell
pip install -r version-tracker/requirements.txt
python version-tracker/tracker.py --config version-tracker/apps.json --html-source path\to\index.html
```

The batch file under `scripts/` illustrates the same invocation so you can reuse it when you run the tracker manually.

## Customization tips
- Add apps to `apps.json`. Each app can provide `name`, `package`, `current_version`, `gamedva_slug`, and (optionally) a `notes` field.
- If you prefer live checks instead of parsing HTML, skip `--html-source`. The tracker will fetch `https://gamedva.com/<gamedva_slug>` and try to extract the latest version automatically.
- The HTML report template can be tweaked inside `tracker.py` should you need to match the styling of the notifications you already send.

Feel free to copy `scripts/run-tracker.bat` into your daily workflow and point it to the latest HTML/telegram dump you already receive.
