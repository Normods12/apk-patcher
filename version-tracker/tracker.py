import argparse
import datetime
import html
import json
import os
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

VERSION_PATTERN = re.compile(r"[\d]+(?:[.\-][\d]+)*")


def load_apps_config(path: Path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    apps = []
    for entry in raw:
        if not entry.get("name") or not entry.get("gamedva_slug"):
            raise ValueError("Each app entry must have at least `name` and `gamedva_slug`.")
        apps.append(
            {
                "name": entry["name"],
                "package": entry.get("package"),
                "current_version": entry.get("current_version"),
                "notes": entry.get("notes"),
                "gamedva_slug": entry["gamedva_slug"].strip("/"),
                "gamedva_url": entry.get("gamedva_url"),
            }
        )
    return apps


def extract_version_from_string(text: str):
    if not text:
        return None
    match = VERSION_PATTERN.search(text)
    return match.group(0) if match else None


def extract_latest_version_from_page(text: str):
    soup = BeautifulSoup(text, "html.parser")
    candidates = []
    og_title = soup.select_one('meta[property="og:title"]')
    if og_title and og_title.get("content"):
        candidates.append(og_title["content"])
    title = soup.find("title")
    if title and title.text:
        candidates.append(title.text)
    for header in soup.find_all(["h1", "h2", "strong"]):
        if header.text:
            candidates.append(header.text)
    for candidate in candidates:
        version = extract_version_from_string(candidate)
        if version:
            return version
    return None


def fetch_from_gamedva(app, session):
    url = app.get("gamedva_url") or f"https://gamedva.com/{app['gamedva_slug']}"
    try:
        response = session.get(url, timeout=15)
    except requests.RequestException:
        return app, None, "unavailable", url
    if response.status_code != 200:
        return app, None, "unavailable", url
    latest_version = extract_latest_version_from_page(response.text)
    return app, latest_version, "available", url


def parse_html_source(path: Path):
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    cards = soup.select("div.card")
    parsed = []
    for card in cards:
        title_tag = card.select_one(".title")
        name = title_tag.text.strip() if title_tag else "Unknown"
        versions_tag = card.select_one(".versions")
        versions_text = versions_tag.get_text(" ", strip=True) if versions_tag else ""
        current_match = re.search(r"You have:\s*([^\s]+)", versions_text)
        official_match = re.search(r"Official:\s*([^\s<]+)", versions_text)
        current_version = current_match.group(1) if current_match else None
        official_version = official_match.group(1) if official_match else None
        links = card.select("a")
        gamedva_link = links[-1]["href"] if links else None
        status = "available"
        card_note = card.get("class", [])
        if "outdated" in card_note:
            status = "needs_update"
        parsed.append(
            {
                "name": name,
                "package": None,
                "current_version": current_version,
                "latest_version": official_version,
                "status": status,
                "gamedva_url": gamedva_link,
            }
        )
    return parsed


def build_snapshot(entries, timestamp: str):
    return {
        "snapshot_at": timestamp,
        "entries": entries,
    }


def summarize_entries(entries):
    summary = {"available": 0, "needs_update": 0, "unavailable": 0, "new": 0, "updated": 0, "unchanged": 0}
    for entry in entries:
        status = entry.get("status")
        change = entry.get("change", "unchanged")
        summary.setdefault(status, 0)
        summary.setdefault(change, 0)
        summary[status] = summary.get(status, 0) + 1
        summary[change] = summary.get(change, 0) + 1
    return summary


def find_previous_snapshot(data_dir: Path, today_path: Path):
    snapshots = sorted([p for p in data_dir.glob("*.json") if p != today_path])
    return snapshots[-1] if snapshots else None


def compare_with_previous(current_entries, previous_entries):
    prev_map = {
        (entry.get("name"), entry.get("package")): entry for entry in previous_entries
    }
    for entry in current_entries:
        key = (entry.get("name"), entry.get("package"))
        prior = prev_map.get(key)
        if not prior:
            entry["change"] = "new"
            continue
        if entry.get("latest_version") and prior.get("latest_version") and entry["latest_version"] != prior["latest_version"]:
            entry["change"] = "updated"
        else:
            entry["change"] = "unchanged"
    return current_entries


def write_snapshot(snapshot, path: Path):
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")


def escape(text: str):
    return html.escape(text or "")


def render_report(snapshot, previous_snapshot_path: Path | None, report_path: Path):
    summary = summarize_entries(snapshot["entries"])
    lines = []
    for entry in snapshot["entries"]:
        latest_version = entry.get("latest_version") or "unknown"
        current_version = entry.get("current_version") or "unknown"
        change = entry.get("change", "unchanged")
        status = entry.get("status", "unavailable")
        card_class = "card"
        if status == "unavailable":
            card_class += " unavailable"
        elif change == "updated":
            card_class += " updated"
        elif status == "needs_update":
            card_class += " needs-update"
        else:
            card_class += " available"
        lines.append(
            f"""\
        <div class="{card_class}">
            <div class="info">
                <div class="title">{escape(entry.get("name"))}</div>
                <div class="versions">
                    current: <strong>{escape(current_version)}</strong><br/>
                    latest: <strong>{escape(latest_version)}</strong>
                </div>
                <div class="status">status: {escape(status)} / change: {escape(change)}</div>
                <div class="notes">{escape(entry.get("notes"))}</div>
            </div>
            <div class="actions">
                <a href="{escape(entry.get("gamedva_url"))}" target="_blank">gamedva</a>
            </div>
        </div>"""
        )
    report_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <title>Gamedva Tracker {snapshot["snapshot_at"]}</title>
    <style>
        body {{ font-family: 'Segoe UI', system-ui, sans-serif; background:#f7f8fb; margin:0; padding:20px; }}
        header {{ margin-bottom:20px; }}
        h1 {{ margin:0; }}
        .summary {{ color:#555; margin-bottom:15px; }}
        .card {{ background:white; border-radius:10px; padding:15px; margin-bottom:12px; box-shadow:0 1px 4px rgba(0,0,0,0.08); display:flex; justify-content:space-between; }}
        .card.updated {{ border-left:6px solid #2d8f4d; }}
        .card.needs-update {{ border-left:6px solid #ff7a18; }}
        .card.unavailable {{ border-left:6px solid #ff4d4f; }}
        .card.available {{ border-left:6px solid #2c7cc0; }}
        .title {{ font-weight:600; font-size:1.1rem; }}
        .versions {{ color:#444; margin-top:6px; font-size:0.95rem; }}
        .status {{ font-size:0.85rem; color:#666; margin-top:4px; }}
        .actions a {{ font-size:0.85rem; color:#1f7ef3; text-decoration:none; }}
        .notes {{ font-size:0.8rem; color:#888; margin-top:4px; }}
        footer {{ margin-top:25px; color:#666; font-size:0.85rem; }}
    </style>
</head>
<body>
    <header>
        <h1>Gamedva Version Snapshot</h1>
        <p class="summary">
            run at {escape(snapshot["snapshot_at"])} · {len(snapshot["entries"])} apps tracked · updated: {summary.get("updated",0)}, still pending: {summary.get("needs_update",0)}, unavailable: {summary.get("unavailable",0)}
        </p>
    </header>
    <section class="list">
{"".join(lines)}
    </section>
    <footer>
        Source snapshot: {Path(report_path.name).name}. Previous snapshot: {previous_snapshot_path.name if previous_snapshot_path else "none"}.
    </footer>
</body>
</html>"""
    report_path.write_text(report_html, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Gamedva version tracker.")
    parser.add_argument("--config", type=Path, default=Path("version-tracker/apps.json"))
    parser.add_argument("--data-dir", type=Path, default=Path("version-tracker/data"))
    parser.add_argument("--report-dir", type=Path, default=Path("version-tracker/reports"))
    parser.add_argument("--html-source", type=Path, help="Optional HTML dump to parse instead of live fetch.")
    parser.add_argument("--force", action="store_true", help="Regenerate today's snapshot even if it exists.")
    args = parser.parse_args()

    if not args.config.exists():
        print(f"config file {args.config} missing.", file=sys.stderr)
        sys.exit(1)

    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_file = args.data_dir / f"{datetime.date.today().isoformat()}.json"

    if today_file.exists() and not args.force:
        print(f"Snapshot for {today_file.name} already exists. Use --force to overwrite.")
        sys.exit(0)

    entries = []
    if args.html_source:
        entries = parse_html_source(args.html_source)
    else:
        apps = load_apps_config(args.config)
        session = requests.Session()
        for app in apps:
            base_app, latest_version, status, resolved_url = fetch_from_gamedva(app, session)
            entries.append(
                {
                    "name": base_app.get("name"),
                    "package": base_app.get("package"),
                    "current_version": base_app.get("current_version"),
                    "latest_version": latest_version,
                    "status": status,
                    "gamedva_url": resolved_url,
                    "notes": base_app.get("notes"),
                }
            )

    snapshot = build_snapshot(entries, timestamp)
    prev_snapshot_path = find_previous_snapshot(args.data_dir, today_file)
    if prev_snapshot_path:
        previous = json.loads(prev_snapshot_path.read_text(encoding="utf-8"))
        snapshot["entries"] = compare_with_previous(snapshot["entries"], previous.get("entries", []))
    else:
        for entry in snapshot["entries"]:
            entry["change"] = "new"
    write_snapshot(snapshot, today_file)

    report_name = f"report-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.html"
    report_path = args.report_dir / report_name
    render_report(snapshot, prev_snapshot_path, report_path)

    print(f"Snapshot saved to {today_file}")
    print(f"Report generated at {report_path}")


if __name__ == "__main__":
    main()
