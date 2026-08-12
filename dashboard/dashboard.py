#!/usr/bin/env python3
"""
Job Search Pipeline Dashboard
Serves a local Kanban view of applied_jobs.db at http://localhost:8787
Status update buttons POST back to update the DB in-place.

Usage:
  python3 dashboard/dashboard.py
  # Opens browser automatically. Ctrl-C to stop.
"""

import sqlite3
import webbrowser
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
from pathlib import Path

import os as _os
DB_PATH = _os.environ.get(
    "DASHBOARD_DB",
    str(Path(__file__).parent.parent / "applied_jobs.db"),
)

VALID_STATUSES = {"applied", "responded", "interviewed", "offered", "rejected", "skipped"}

NEXT_ACTIONS = {
    "applied":     [("responded", "Responded"), ("rejected", "Rejected")],
    "responded":   [("interviewed", "Interviewed"), ("rejected", "Rejected")],
    "interviewed": [("offered", "Offered"), ("rejected", "Rejected")],
}

TIER_COLORS = {
    "STRONG":   "#22c55e",
    "GOOD":     "#f59e0b",
    "POSSIBLE": "#ef4444",
}


def _query(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _card(job):
    url     = job["url"]
    title   = job.get("title") or "Role"
    company = job.get("company") or ""
    acted   = job.get("date_acted") or job.get("date_seen") or ""
    tier    = (job.get("tier") or "").upper().replace("\U0001f7e2", "").replace("\U0001f7e1", "").replace("\U0001f7e0", "").strip()
    score   = job.get("score") or ""
    status  = job.get("status", "")

    tier_clean = tier.split()[0] if tier else ""
    badge_color = TIER_COLORS.get(tier_clean, "#6b7280")

    buttons_html = ""
    for new_status, label in NEXT_ACTIONS.get(status, []):
        buttons_html += (
            f'<form method="POST" action="/update" style="display:inline">'
            f'<input type="hidden" name="url" value="{url}">'
            f'<input type="hidden" name="status" value="{new_status}">'
            f'<button type="submit" class="btn btn-{new_status}">{label}</button>'
            f'</form>'
        )

    return f"""
<div class="card">
  <div class="card-header">
    <span class="company">{company}</span>
    <span class="badge" style="background:{badge_color}">{score}</span>
  </div>
  <div class="title"><a href="{url}" target="_blank">{title}</a></div>
  <div class="date">{acted}</div>
  <div class="card-actions">{buttons_html}</div>
</div>"""


def _column(label, jobs):
    cards = "".join(_card(j) for j in jobs)
    count = len(jobs)
    return f"""
<div class="column">
  <div class="col-header">{label} <span class="count">{count}</span></div>
  <div class="col-body">{cards if cards else '<p class="empty">—</p>'}</div>
</div>"""


def build_page(db_path: str) -> str:
    """Query `db_path` and return a full HTML page string."""
    all_jobs = _query(db_path,
        "SELECT * FROM jobs WHERE status NOT IN ('new','skipped') ORDER BY date_acted DESC"
    )

    by_status = {}
    for j in all_jobs:
        by_status.setdefault(j["status"], []).append(j)

    applied_jobs     = by_status.get("applied", [])
    responded_jobs   = by_status.get("responded", [])
    interviewed_jobs = by_status.get("interviewed", [])
    offered_jobs     = by_status.get("offered", [])
    rejected_jobs    = by_status.get("rejected", [])

    responded_n   = len(responded_jobs) + len(interviewed_jobs) + len(offered_jobs)
    interviewed_n = len(interviewed_jobs) + len(offered_jobs)

    def pct(num, denom):
        if denom == 0:
            return "—"
        return f"{round(num / denom * 100)}%"

    response_rate  = pct(responded_n, len(all_jobs))
    interview_rate = pct(interviewed_n, len(all_jobs))

    # Source breakdown
    source_rows = _query(db_path,
        "SELECT source, COUNT(*) as n FROM jobs "
        "WHERE status NOT IN ('new','skipped','rejected') "
        "GROUP BY source ORDER BY n DESC"
    )
    source_html = "".join(
        f"<tr><td>{r['source']}</td><td>{r['n']}</td></tr>"
        for r in source_rows
    )

    columns_html = (
        _column("Applied", applied_jobs)
        + _column("Responded", responded_jobs)
        + _column("Interviewed", interviewed_jobs)
        + _column("Offered", offered_jobs)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Search Pipeline</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background: #f1f5f9; color: #1e293b; min-height: 100vh; }}
  header {{ background: #0f172a; color: #f8fafc; padding: 1rem 1.5rem;
            display: flex; align-items: center; gap: 2rem; }}
  header h1 {{ font-size: 1.1rem; font-weight: 600; }}
  .stat {{ text-align: center; }}
  .stat-val {{ font-size: 1.6rem; font-weight: 700; }}
  .stat-label {{ font-size: 0.7rem; opacity: 0.7; text-transform: uppercase; letter-spacing: .05em; }}
  .board {{ display: flex; gap: 1rem; padding: 1rem 1.5rem; overflow-x: auto; align-items: flex-start; }}
  .column {{ flex: 0 0 280px; background: #e2e8f0; border-radius: 8px; overflow: hidden; }}
  .col-header {{ padding: .6rem 1rem; font-weight: 600; font-size: .85rem;
                  background: #cbd5e1; display: flex; justify-content: space-between; }}
  .count {{ background: #64748b; color: #fff; border-radius: 99px;
             padding: 0 6px; font-size: .75rem; }}
  .col-body {{ padding: .5rem; display: flex; flex-direction: column; gap: .5rem; min-height: 60px; }}
  .empty {{ color: #94a3b8; font-size: .8rem; padding: .5rem; text-align: center; }}
  .card {{ background: #fff; border-radius: 6px; padding: .75rem;
            box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  .card-header {{ display: flex; justify-content: space-between; align-items: center;
                   margin-bottom: .3rem; }}
  .company {{ font-weight: 600; font-size: .85rem; }}
  .badge {{ color: #fff; font-size: .7rem; font-weight: 700;
             padding: 2px 6px; border-radius: 99px; }}
  .title a {{ font-size: .8rem; color: #3b82f6; text-decoration: none; }}
  .title a:hover {{ text-decoration: underline; }}
  .date {{ font-size: .7rem; color: #94a3b8; margin-top: .2rem; }}
  .card-actions {{ margin-top: .5rem; display: flex; gap: .3rem; flex-wrap: wrap; }}
  .btn {{ border: none; border-radius: 4px; padding: 3px 8px;
           font-size: .72rem; cursor: pointer; font-weight: 500; }}
  .btn-responded   {{ background: #dbeafe; color: #1d4ed8; }}
  .btn-interviewed {{ background: #d1fae5; color: #065f46; }}
  .btn-offered     {{ background: #fef3c7; color: #92400e; }}
  .btn-rejected    {{ background: #fee2e2; color: #991b1b; }}
  .btn:hover {{ filter: brightness(.92); }}
  .rejected-bar {{ padding: .5rem 1.5rem 1rem; font-size: .8rem; color: #64748b; }}
  .sources {{ padding: 1rem 1.5rem 2rem; }}
  .sources h2 {{ font-size: .85rem; font-weight: 600; margin-bottom: .5rem; }}
  .sources table {{ border-collapse: collapse; font-size: .8rem; }}
  .sources td {{ padding: .25rem .75rem; border-bottom: 1px solid #e2e8f0; }}
  .sources tr:first-child td {{ font-weight: 600; }}
</style>
</head>
<body>
<header>
  <h1>Job Search Pipeline</h1>
  <div class="stat"><div class="stat-val">{len(all_jobs)}</div><div class="stat-label">Total Applied</div></div>
  <div class="stat"><div class="stat-val">{response_rate}</div><div class="stat-label">Response Rate</div></div>
  <div class="stat"><div class="stat-val">{interview_rate}</div><div class="stat-label">Interview Rate</div></div>
</header>
<div class="board">{columns_html}</div>
<div class="rejected-bar">Rejected / withdrawn: {len(rejected_jobs)}</div>
<div class="sources">
  <h2>Applications by source</h2>
  <table><tr><td>Source</td><td>Count</td></tr>{source_html}</table>
</div>
</body>
</html>"""


def make_handler(db_path: str):
    """Return a request handler class bound to the given db_path."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # silence default access log
            pass

        def do_GET(self):
            if self.path == "/":
                html = build_page(db_path).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path == "/update":
                length = int(self.headers.get("Content-Length", 0))
                body   = self.rfile.read(length).decode()
                params = parse_qs(body)
                url    = params.get("url",    [""])[0]
                status = params.get("status", [""])[0]
                if url and status in VALID_STATUSES:
                    conn = sqlite3.connect(db_path)
                    conn.execute(
                        "UPDATE jobs SET status=?, date_acted=? WHERE url=?",
                        (status, time.strftime("%Y-%m-%d"), url)
                    )
                    conn.commit()
                    conn.close()
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
            else:
                self.send_error(404)

    return Handler


def make_server(host: str, port: int, db_path: str) -> HTTPServer:
    return HTTPServer((host, port), make_handler(db_path))


def main():
    port = 8787
    url  = f"http://localhost:{port}"
    server = make_server("127.0.0.1", port, DB_PATH)
    print(f"Dashboard running at {url}  (Ctrl-C to stop)")
    threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
