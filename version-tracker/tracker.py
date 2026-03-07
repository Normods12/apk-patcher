import argparse
import datetime
import html
import json
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


def normalize_slug_from_url(url: str | None):
    if not url:
        return None
    parsed = requests.utils.urlparse(url)
    if not parsed.path:
        return None
    slug = parsed.path.strip("/")
    return slug.split("/")[-1].lower() if slug else None


def parse_html_source(path: Path):
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    cards = soup.select("div.card")
    parsed = {}
    for card in cards:
        versions_tag = card.select_one(".versions")
        versions_text = versions_tag.get_text(" ", strip=True) if versions_tag else ""
        official_match = re.search(r"Official:\s*([^\s<]+)", versions_text)
        official_version = official_match.group(1) if official_match else None
        links = card.select("a")
        gamedva_link = links[-1]["href"] if links else None
        slug = normalize_slug_from_url(gamedva_link)
        if not slug:
            continue
        parsed[slug] = {
            "latest_version": official_version,
            "gamedva_url": gamedva_link,
        }
    return parsed


def build_entries_from_html(apps, html_lookup):
    entries = []
    missing = []
    for app in apps:
        slug = app["gamedva_slug"].lower()
        html_entry = html_lookup.get(slug)
        if not html_entry:
            missing.append(app["name"])
            continue
        latest_version = html_entry.get("latest_version")
        current_version = app.get("current_version")
        if latest_version and current_version and latest_version == current_version:
            status = "available"
        elif latest_version:
            status = "needs_update"
        else:
            status = "unavailable"
        entries.append(
            {
                "name": app.get("name"),
                "package": app.get("package"),
                "current_version": current_version,
                "latest_version": latest_version,
                "status": status,
                "gamedva_url": html_entry.get("gamedva_url"),
                "notes": app.get("notes"),
            }
        )
    return entries, missing


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
    prev_map = {(entry.get("name"), entry.get("package")): entry for entry in previous_entries}
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
    status_labels = {
        "needs_update": "Needs Update",
        "available": "Up to Date",
        "unavailable": "Unavailable",
    }
    change_labels = {
        "new": "New entry",
        "updated": "Version changed since last run",
        "unchanged": "No change since previous snapshot",
    }
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
        status_label = status_labels.get(status, status.replace("_", " ").title())
        change_label = change_labels.get(change, change.title())
        status_class = status.replace("_", "-")
        notes_html = f'<div class="notes">{escape(entry.get("notes"))}</div>' if entry.get("notes") else ""
        lines.append(
            f"""\
        <div class="{card_class}">
            <div class="info">
                <div class="title">{escape(entry.get("name"))}</div>
                <div class="versions">
                    <span class="current">current:</span> <strong>{escape(current_version)}</strong><br/>
                    <span class="latest">latest:</span> <strong>{escape(latest_version)}</strong>
                </div>
                <div class="status-line">
                    <span class="status-tag {status_class}">{escape(status_label)}</span>
                    <span class="change-tag">{escape(change_label)}</span>
                </div>
                {notes_html}
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
        .card {{ background:white; border-radius:10px; padding:20px; margin-bottom:14px; box-shadow:0 1px 6px rgba(0,0,0,0.08); display:flex; justify-content:space-between; gap:20px; }}
        .card.updated {{ border-left:6px solid #2d8f4d; }}
        .card.needs-update {{ border-left:6px solid #ff7a18; }}
        .card.unavailable {{ border-left:6px solid #ff4d4f; }}
        .card.available {{ border-left:6px solid #2c7cc0; }}
        .info {{ flex:1; }}
        .title {{ font-weight:700; font-size:1.25rem; margin-bottom:4px; }}
        .list {{ display:flex; flex-direction:column; }}
        .versions {{ color:#222; margin-top:6px; font-size:0.95rem; line-height:1.4; }}
        .versions .current, .versions .latest {{ font-size:0.85rem; color:#666; text-transform:uppercase; letter-spacing:0.1em; }}
        .status-line {{ margin-top:12px; display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
        .status-tag {{ font-size:1rem; font-weight:700; padding:6px 14px; border-radius:999px; }}
        .status-tag.needs-update {{ background:#ffe5de; color:#c0351a; }}
        .status-tag.available {{ background:#e9f5ff; color:#0d4f7a; }}
        .status-tag.unavailable {{ background:#fff4cc; color:#a8701b; }}
        .change-tag {{ font-size:0.85rem; color:#555; }}
        .notes {{ margin-top:10px; font-size:0.85rem; color:#666; }}
        .actions {{ display:flex; align-items:flex-start; min-width:110px; }}
        .actions a {{ font-size:0.9rem; color:#1761d8; text-decoration:none; font-weight:600; }}
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
        Snapshot: {report_path.name}. Previous: {previous_snapshot_path.name if previous_snapshot_path else "none"}.
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

    apps = load_apps_config(args.config)
    entries = []
    if args.html_source:
        html_lookup = parse_html_source(args.html_source)
        entries, missing = build_entries_from_html(apps, html_lookup)
        if missing:
            print(f"Skipping {len(missing)} apps not present in HTML source: {', '.join(missing)}")
    else:
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
