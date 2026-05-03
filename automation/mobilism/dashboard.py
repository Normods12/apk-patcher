import http.server
import socketserver
import sqlite3
from urllib.parse import urlparse, parse_qs
from automation.mobilism.config import DASHBOARD_PORT, DB_PATH
from automation.mobilism.db import get_connection

def get_new_apps():
    apps = []
    if not DB_PATH.exists():
        return []
        
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM mobilism_apps WHERE status = 'NEW' ORDER BY first_seen DESC"
            ).fetchall()
            for row in rows:
                apps.append(dict(row))
    except Exception as e:
        print(f"DB Error: {e}")
    return apps

class MobilismDashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            
            apps = get_new_apps()
            
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Mobilism Monitor</title>
                <meta http-equiv="refresh" content="30">
                <style>
                    body {{ font-family: sans-serif; padding: 20px; background: #f4f4f9; }}
                    h1 {{ color: #333; }}
                    table {{ width: 100%; border-collapse: collapse; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
                    th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
                    th {{ background-color: #007bff; color: white; }}
                    tr:hover {{ background-color: #f1f1f1; }}
                    a {{ color: #007bff; text-decoration: none; }}
                    .tag {{ padding: 4px 8px; border-radius: 4px; font-size: 0.85em; font-weight: bold; background: #28a745; color: white; }}
                    .empty {{ padding: 20px; text-align: center; color: #666; }}
                </style>
            </head>
            <body>
                <h1>Mobilism vs GameDVA Monitor</h1>
                <p>Showing apps found on Mobilism that are <strong>NOT</strong> yet on GameDVA.</p>
                
                <table>
                    <thead>
                        <tr>
                            <th>App Name</th>
                            <th>Version</th>
                            <th>Status</th>
                            <th>Found At</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            
            if not apps:
                html += '<tr><td colspan="5" class="empty">No new updates found yet. Check back later!</td></tr>'
            else:
                for app in apps:
                    html += f"""
                        <tr>
                            <td>{app['app_name']}</td>
                            <td>{app['version']}</td>
                            <td><span class="tag">{app['status']}</span></td>
                            <td>{app['first_seen']}</td>
                            <td><a href="{app['url']}" target="_blank">View on Mobilism</a></td>
                        </tr>
                    """
            
            html += """
                    </tbody>
                </table>
            </body>
            </html>
            """
            
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_error(404)

def run_dashboard():
    with socketserver.TCPServer(("", DASHBOARD_PORT), MobilismDashboardHandler) as httpd:
        print(f"Mobilism Dashboard running at http://localhost:{DASHBOARD_PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    run_dashboard()
