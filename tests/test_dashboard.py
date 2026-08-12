import os
import sys
import sqlite3
import tempfile
import threading
import urllib.request
import urllib.parse
import urllib.error
from http.server import HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "dashboard"))
from dashboard import build_page, make_handler, make_server


def _make_test_db(rows):
    """Create a temp SQLite DB with the jobs schema and given rows. Returns path."""
    db_path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            title TEXT,
            company TEXT,
            source TEXT,
            score INTEGER,
            tier TEXT,
            status TEXT,
            date_seen TEXT,
            date_acted TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()
    return db_path


def test_build_page_shows_applied_job():
    db = _make_test_db([
        ("http://ex.com/1", "QE Lead", "Acme", "LinkedIn", 80, "STRONG",
         "applied", "2026-08-11", "2026-08-11"),
    ])
    try:
        html = build_page(db)
        assert "Acme" in html
        assert "QE Lead" in html
    finally:
        os.unlink(db)


def test_build_page_shows_response_rate():
    db = _make_test_db([
        ("http://ex.com/1", "QE Lead", "Acme", "LinkedIn", 80, "STRONG",
         "applied", "2026-08-11", "2026-08-11"),
        ("http://ex.com/2", "SDET", "Beta", "Greenhouse", 70, "GOOD",
         "responded", "2026-08-11", "2026-08-12"),
    ])
    try:
        html = build_page(db)
        assert "50%" in html  # 1 responded / 2 applied
    finally:
        os.unlink(db)


def test_build_page_empty_db():
    db = _make_test_db([])
    try:
        html = build_page(db)
        assert "Applied" in html   # columns still render
        assert "0" in html
    finally:
        os.unlink(db)


def test_post_update_changes_status():
    db = _make_test_db([
        ("http://ex.com/1", "QE Lead", "Acme", "LinkedIn", 80, "STRONG",
         "applied", "2026-08-11", "2026-08-11"),
    ])
    try:
        server = make_server("127.0.0.1", 18787, db)
        t = threading.Thread(target=server.handle_request)
        t.daemon = True
        t.start()

        data = urllib.parse.urlencode(
            {"url": "http://ex.com/1", "status": "responded"}
        ).encode()
        try:
            urllib.request.urlopen(
                "http://127.0.0.1:18787/update", data=data, timeout=3
            )
        except urllib.error.HTTPError:
            pass  # 302 redirect raises HTTPError — that's expected

        t.join(timeout=2)
        server.server_close()

        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT status FROM jobs WHERE url='http://ex.com/1'"
        ).fetchone()
        conn.close()
        assert row[0] == "responded"
    finally:
        os.unlink(db)
