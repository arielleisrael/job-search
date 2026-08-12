# Phase 3 Quality Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tailored Claude API cover notes, automatic resume variant switching, and a local pipeline dashboard to the job search automation system.

**Architecture:** Two self-contained additions to `autofiller/autofiller.py` (resume picking and cover note generation share a module-level `_JOB_INFO` dict that `_prefill_page` populates before each handler runs and `scroll_and_fill_all` reads). The dashboard is a brand-new `dashboard/dashboard.py` file using only stdlib.

**Tech Stack:** Python 3, `anthropic` SDK (cover notes), stdlib `http.server` + `sqlite3` + `webbrowser` (dashboard), `pytest` + `unittest.mock` (tests)

## Global Constraints

- `PROFILE["cover_note"]` and `PROFILE["resume_path"]` must NEVER be mutated — per-job overrides are injected locally only
- User always reviews and submits — no auto-submit under any circumstances
- Dashboard binds to `127.0.0.1` only (never `0.0.0.0`)
- Cover note generation falls back to `PROFILE["cover_note"]` on any API error — applications must never fail due to Claude API issues
- Missing resume PDFs print a warning but do not abort — autofiller falls back to whatever file is valid
- No new dependencies for the dashboard (stdlib only); `anthropic` is the only new package for the autofiller
- Model for cover note generation: `claude-haiku-4-5-20251001`

---

## File Map

| File | Status | Responsibility |
|------|--------|----------------|
| `autofiller/autofiller.py` | Modify | Add `pick_resume`, `pick_cover_note`, `_JOB_INFO` integration, `--resume` flag, startup checks |
| `dashboard/dashboard.py` | Create | Stdlib HTTP server + inline HTML dashboard fed from `applied_jobs.db` |
| `tests/test_autofiller.py` | Create | Unit tests for `pick_resume` and `pick_cover_note` |
| `tests/test_dashboard.py` | Create | Unit/integration tests for `build_page` and POST `/update` |

---

## Task 1: Resume Variant Switching

**Files:**
- Modify: `autofiller/autofiller.py:20-26` (imports), `autofiller.py:118` (after PROFILE block), `autofiller.py:313-322` (`scroll_and_fill_all`), `autofiller.py:586-602` (`_prefill_page`), `autofiller.py:821-865` (`main`)
- Create: `tests/test_autofiller.py`

**Interfaces:**
- Produces: `pick_resume(title: str) -> str` — pure function, returns absolute path to resume PDF
- Produces: `_JOB_INFO: dict` — module-level dict with keys `title`, `company`, `resume_path`; populated by `_prefill_page` before each handler call, cleared after

- [ ] **Step 1: Write the failing tests**

Create `tests/test_autofiller.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "autofiller"))

from autofiller import pick_resume, RESUME_DEFAULT, RESUME_VARIANTS, RESUME_BASE


def test_pick_resume_manager():
    result = pick_resume("Senior QE Manager")
    assert result.endswith("Resume-QE-Manager-ArielleIsrael.pdf")


def test_pick_resume_director():
    result = pick_resume("Director of Quality Engineering")
    assert result.endswith("Resume-QE-Manager-ArielleIsrael.pdf")


def test_pick_resume_lead():
    result = pick_resume("Lead SDET")
    assert result.endswith("Resume-Lead-SDET-ArielleIsrael.pdf")


def test_pick_resume_staff():
    result = pick_resume("Staff Quality Engineer")
    assert result.endswith("Resume-Lead-SDET-ArielleIsrael.pdf")


def test_pick_resume_principal():
    result = pick_resume("Principal Software Engineer in Test")
    assert result.endswith("Resume-Lead-SDET-ArielleIsrael.pdf")


def test_pick_resume_default():
    result = pick_resume("Senior Quality Engineer")
    assert result.endswith("Resume-Senior-Quality-Engineer-ArielleIsrael.pdf")


def test_pick_resume_case_insensitive():
    result = pick_resume("MANAGER quality engineering")
    assert result.endswith("Resume-QE-Manager-ArielleIsrael.pdf")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/arielleisrael/job-search
python -m pytest tests/test_autofiller.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'pick_resume'`

- [ ] **Step 3: Add imports, constants, and `pick_resume` to autofiller.py**

Add `import os` after the existing `import sqlite3` line (~line 25):

```python
import os
```

Add the following block immediately after the `PROFILE = { ... }` dict (after line ~136, before `FIELD_MAP`):

```python
# ── RESUME VARIANTS ────────────────────────────────────────────────────────
RESUME_BASE = Path.home() / "job-search"
RESUME_DEFAULT = "Resume-Senior-Quality-Engineer-ArielleIsrael.pdf"
RESUME_VARIANTS = {
    "manager":   "Resume-QE-Manager-ArielleIsrael.pdf",
    "director":  "Resume-QE-Manager-ArielleIsrael.pdf",
    "lead":      "Resume-Lead-SDET-ArielleIsrael.pdf",
    "staff":     "Resume-Lead-SDET-ArielleIsrael.pdf",
    "principal": "Resume-Lead-SDET-ArielleIsrael.pdf",
}
RESUME_FORCE_MAP = {
    "ic":      str(RESUME_BASE / RESUME_DEFAULT),
    "manager": str(RESUME_BASE / "Resume-QE-Manager-ArielleIsrael.pdf"),
    "lead":    str(RESUME_BASE / "Resume-Lead-SDET-ArielleIsrael.pdf"),
}
_RESUME_FORCED = None   # set from --resume flag in main()

# ── PER-JOB OVERRIDES (module-level, single-threaded safe) ────────────────
# Populated by _prefill_page before each handler call; read by scroll_and_fill_all.
_JOB_INFO: dict = {}


def pick_resume(title: str) -> str:
    """Return the absolute path to the best resume PDF for this job title."""
    if _RESUME_FORCED:
        return _RESUME_FORCED
    t = title.lower()
    for keyword, filename in RESUME_VARIANTS.items():
        if keyword in t:
            return str(RESUME_BASE / filename)
    return str(RESUME_BASE / RESUME_DEFAULT)
```

- [ ] **Step 4: Modify `scroll_and_fill_all` to use `_JOB_INFO` resume path**

Replace the existing `scroll_and_fill_all` function (lines ~313-322):

```python
def scroll_and_fill_all(page):
    """Walk through FIELD_MAP and fill whatever fields are on the page."""
    resume_path = _JOB_INFO.get("resume_path") or PROFILE["resume_path"]

    filled = 0
    for label_patterns, value in FIELD_MAP:
        if find_and_fill_by_label(page, label_patterns, value):
            filled += 1
            time.sleep(0.3)
    handle_yes_no_radios(page)
    attach_resume(page, resume_path)
    return filled
```

- [ ] **Step 5: Modify `_prefill_page` to populate `_JOB_INFO`**

Replace the existing `_prefill_page` function body (lines ~586-602). Add `global _JOB_INFO` and the setup/teardown of the dict around the handler call:

```python
def _prefill_page(page, job_info):
    """
    Navigate to job_info['url'] and pre-fill the form on an already-open page.
    Prints the job header and calls the appropriate platform handler.
    """
    global _JOB_INFO

    url = job_info.get("url", "") if isinstance(job_info, dict) else str(job_info)

    if isinstance(job_info, dict) and (job_info.get("title") or job_info.get("company")):
        print(f"\n{'─'*60}")
        print(f"  {job_info.get('title', 'Role')} @ {job_info.get('company', '')}")
        print(f"  Score: {job_info.get('score', '?')}/100  |  {job_info.get('source', '')}")
        print(f"  {url}")
        print(f"{'─'*60}")

    if isinstance(job_info, dict):
        _JOB_INFO = {
            "title":       job_info.get("title", ""),
            "company":     job_info.get("company", ""),
            "resume_path": pick_resume(job_info.get("title", "")),
        }
    else:
        _JOB_INFO = {}

    try:
        platform = detect_platform(url)
        handler = HANDLERS[platform]
        handler(page, url)
    finally:
        _JOB_INFO = {}
```

- [ ] **Step 6: Add `--resume` flag and startup validation to `main()`**

In `main()`, add the `--resume` argument after the existing `--batch` argument:

```python
parser.add_argument(
    "--resume", choices=["ic", "manager", "lead"], default=None,
    help="Force a specific resume variant for this session (overrides auto-detection)"
)
```

After the `--batch` range check, add:

```python
global _RESUME_FORCED
if args.resume:
    _RESUME_FORCED = RESUME_FORCE_MAP[args.resume]

# Validate all resume PDFs exist
for label, path in [
    ("IC",      str(RESUME_BASE / RESUME_DEFAULT)),
    ("Manager", str(RESUME_BASE / "Resume-QE-Manager-ArielleIsrael.pdf")),
    ("Lead",    str(RESUME_BASE / "Resume-Lead-SDET-ArielleIsrael.pdf")),
]:
    if not Path(path).exists():
        print(f"   ⚠  {label} resume not found: {path}")
```

Replace the existing startup resume print block with:

```python
active_resume = _RESUME_FORCED or str(RESUME_BASE / RESUME_DEFAULT)
resume_label = f"forced ({args.resume})" if args.resume else "auto-detect by title"
print(f"\n   Resume selection: {resume_label}")
print(f"   Default/forced path: {active_resume}")
if not Path(active_resume).exists():
    print(f"   ⚠  Resume file not found at that path!")
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
cd /Users/arielleisrael/job-search
python -m pytest tests/test_autofiller.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 8: Smoke-test the CLI flag**

```bash
cd /Users/arielleisrael/job-search
python3 autofiller/autofiller.py --help | grep resume
```

Expected: `--resume {ic,manager,lead}` appears in help output

- [ ] **Step 9: Commit**

```bash
git add autofiller/autofiller.py tests/test_autofiller.py
git commit -m "feat: resume variant switching — pick_resume + --resume flag"
```

---

## Task 2: Claude API Cover Notes

**Files:**
- Modify: `autofiller/autofiller.py` (imports, new function, `scroll_and_fill_all` update, startup check)
- Modify: `tests/test_autofiller.py` (add cover note tests)

**Interfaces:**
- Consumes: `_JOB_INFO` dict (produced by Task 1's `_prefill_page`), with keys `title` and `company`
- Produces: `pick_cover_note(page, job: dict) -> str` — returns 3-sentence tailored note or falls back to `PROFILE["cover_note"]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_autofiller.py`:

```python
import os
from unittest.mock import patch, MagicMock
from autofiller import pick_cover_note, PROFILE


def test_pick_cover_note_returns_api_text():
    mock_page = MagicMock()
    mock_page.inner_text.return_value = "We are building great software and need a QE Lead."
    job = {"title": "QE Lead", "company": "Acme Corp"}

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="  First sentence. Second sentence. Third sentence.  ")]

    with patch("autofiller._anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = mock_msg

        result = pick_cover_note(mock_page, job)

    assert result == "First sentence. Second sentence. Third sentence."


def test_pick_cover_note_falls_back_on_api_exception():
    mock_page = MagicMock()
    mock_page.inner_text.return_value = "Job description text"
    job = {"title": "QE Lead", "company": "Acme Corp"}

    with patch("autofiller._anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.side_effect = Exception("network error")
        result = pick_cover_note(mock_page, job)

    assert result == PROFILE["cover_note"]


def test_pick_cover_note_falls_back_when_anthropic_none():
    mock_page = MagicMock()
    job = {"title": "QE Lead", "company": "Acme Corp"}

    with patch("autofiller._anthropic", None):
        result = pick_cover_note(mock_page, job)

    assert result == PROFILE["cover_note"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/arielleisrael/job-search
python -m pytest tests/test_autofiller.py::test_pick_cover_note_returns_api_text -v
```

Expected: `ImportError: cannot import name 'pick_cover_note'`

- [ ] **Step 3: Add `anthropic` auto-install and import to autofiller.py**

Add the following block immediately after `ensure_playwright()` is defined (before `from playwright.sync_api import ...`):

```python
def _ensure_anthropic():
    try:
        import anthropic  # noqa: F401
    except ImportError:
        if os.environ.get("ANTHROPIC_API_KEY"):
            print("Installing anthropic SDK...")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "anthropic", "-q"]
            )

_ensure_anthropic()

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None
```

- [ ] **Step 4: Add `pick_cover_note` function**

Add the following function immediately after the `pick_resume` function added in Task 1:

```python
def pick_cover_note(page, job: dict) -> str:
    """
    Scrape the job page already open in `page` and call the Claude API to generate
    a 3-sentence tailored cover note. Falls back to PROFILE["cover_note"] on any
    API error or when _anthropic is not available.
    """
    if _anthropic is None:
        return PROFILE["cover_note"]
    try:
        body_text = page.inner_text("body")[:3000]
        title   = job.get("title", "")
        company = job.get("company", "")
        client  = _anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=(
                "You are writing a cover note for a job application. "
                "Write exactly 3 sentences. "
                "Tone: confident, specific, no filler phrases. "
                "Output only the 3 sentences, no preamble."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Candidate: Arielle Israel, QE leader, 17+ years, specializes in "
                    f"Playwright/Cypress/Appium, web + mobile automation, CI/CD, team leadership.\n"
                    f"Job title: {title} at {company}.\n"
                    f"Job description excerpt: {body_text}"
                ),
            }],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"  ⚠ Cover note generation failed: {e} — using default note")
        return PROFILE["cover_note"]
```

- [ ] **Step 5: Modify `scroll_and_fill_all` to inject cover note**

Replace the `scroll_and_fill_all` function that was written in Task 1 with this updated version:

```python
def scroll_and_fill_all(page):
    """Walk through FIELD_MAP and fill whatever fields are on the page."""
    # Per-job overrides — PROFILE is never mutated
    if _JOB_INFO and _anthropic and os.environ.get("ANTHROPIC_API_KEY"):
        cover_note = pick_cover_note(page, _JOB_INFO)
    else:
        cover_note = PROFILE["cover_note"]
    resume_path = _JOB_INFO.get("resume_path") or PROFILE["resume_path"]

    filled = 0
    for label_patterns, value in FIELD_MAP:
        # Swap in the per-job cover note for the cover letter field
        actual_value = cover_note if value == PROFILE["cover_note"] else value
        if find_and_fill_by_label(page, label_patterns, actual_value):
            filled += 1
            time.sleep(0.3)
    handle_yes_no_radios(page)
    attach_resume(page, resume_path)
    return filled
```

- [ ] **Step 6: Add startup check for `ANTHROPIC_API_KEY` in `main()`**

Add after the resume validation block added in Task 1:

```python
if _anthropic is None:
    print("   ⚠  anthropic package not installed — cover notes will use static fallback")
elif not os.environ.get("ANTHROPIC_API_KEY"):
    print("   ⚠  ANTHROPIC_API_KEY not set — cover notes will use static fallback")
else:
    print("   ✅ Claude API ready — cover notes will be tailored per job")
```

- [ ] **Step 7: Run all tests**

```bash
cd /Users/arielleisrael/job-search
python -m pytest tests/test_autofiller.py -v
```

Expected: all 10 tests PASS

- [ ] **Step 8: Commit**

```bash
git add autofiller/autofiller.py tests/test_autofiller.py
git commit -m "feat: Claude API cover note generation per job"
```

---

## Task 3: Pipeline Dashboard

**Files:**
- Create: `dashboard/dashboard.py`
- Create: `tests/test_dashboard.py`

**Interfaces:**
- Produces: `build_page(db_path: str) -> str` — pure function, queries DB, returns full HTML string
- Produces: `make_handler(db_path: str)` — returns an `http.server.BaseHTTPRequestHandler` subclass
- Produces: `make_server(host: str, port: int, db_path: str) -> HTTPServer`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dashboard.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/arielleisrael/job-search
python -m pytest tests/test_dashboard.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'dashboard'`

- [ ] **Step 3: Create `dashboard/dashboard.py`**

Create `/Users/arielleisrael/job-search/dashboard/dashboard.py`:

```python
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
from urllib.parse import urlparse, parse_qs, unquote_plus
from pathlib import Path

DB_PATH = str(Path(__file__).parent.parent / "applied_jobs.db")

VALID_STATUSES = {"applied", "responded", "interviewed", "offered", "rejected", "skipped"}

NEXT_ACTIONS = {
    "applied":    [("responded", "Responded"), ("rejected", "Rejected")],
    "responded":  [("interviewed", "Interviewed"), ("rejected", "Rejected")],
    "interviewed":[("offered", "Offered"), ("rejected", "Rejected")],
}

TIER_COLORS = {
    "STRONG": "#22c55e",
    "GOOD":   "#f59e0b",
    "POSSIBLE": "#ef4444",
}


def _query(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _card(job):
    url     = job["url"]
    title   = job.get("title") or "Role"
    company = job.get("company") or ""
    acted   = job.get("date_acted") or job.get("date_seen") or ""
    tier    = (job.get("tier") or "").upper().replace("🟢", "").replace("🟡", "").replace("🟠", "").strip()
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

    total_applied = len(all_jobs) - len(rejected_jobs)
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
                length  = int(self.headers.get("Content-Length", 0))
                body    = self.rfile.read(length).decode()
                params  = parse_qs(body)
                url     = unquote_plus(params.get("url",     [""])[0])
                status  = unquote_plus(params.get("status",  [""])[0])
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/arielleisrael/job-search
python -m pytest tests/test_dashboard.py -v
```

Expected: all 4 tests PASS

- [ ] **Step 5: Smoke-test the dashboard manually**

```bash
cd /Users/arielleisrael/job-search
python3 dashboard/dashboard.py &
sleep 1
curl -s http://localhost:8787/ | grep -i "pipeline\|applied"
kill %1
```

Expected: HTML page content with "Pipeline" and "Applied" in the output

- [ ] **Step 6: Commit**

```bash
git add dashboard/dashboard.py tests/test_dashboard.py
git commit -m "feat: pipeline dashboard with status update buttons"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ `pick_cover_note` — Task 2
- ✅ Fallback to static note on API error — Task 2, step 4 (exception handler)
- ✅ `ANTHROPIC_API_KEY` startup warning — Task 2, step 6
- ✅ `pick_resume` with all 5 keyword variants — Task 1, step 3
- ✅ `--resume ic|manager|lead` flag — Task 1, step 6
- ✅ Startup validation for all 3 PDFs — Task 1, step 6
- ✅ `PROFILE` never mutated — enforced in `scroll_and_fill_all` (local `cover_note`/`resume_path` vars)
- ✅ Dashboard at `localhost:8787`, `127.0.0.1` only — Task 3, `make_server("127.0.0.1", ...)`
- ✅ `GET /` renders HTML from DB — Task 3
- ✅ `POST /update` writes DB + 302 redirect — Task 3
- ✅ Kanban columns: Applied → Responded → Interviewed → Offered — Task 3 `build_page`
- ✅ Rejected as terminal count at bottom — Task 3 `build_page`
- ✅ Per-card action buttons for each active stage — Task 3 `_card`
- ✅ Header stats: total applied, response rate, interview rate — Task 3 `build_page`
- ✅ Source breakdown table — Task 3 `build_page`
- ✅ Opens browser automatically — Task 3 `main()` with `webbrowser.open`

**Type consistency across tasks:**
- `_JOB_INFO` dict introduced in Task 1 (`_prefill_page`) → read in Task 2 (`scroll_and_fill_all`) ✅
- `pick_resume(title: str) -> str` defined Task 1 → called in `_prefill_page` Task 1 ✅
- `pick_cover_note(page, job: dict) -> str` defined Task 2 → called in `scroll_and_fill_all` Task 2 ✅
- `build_page(db_path: str) -> str` defined Task 3 → tested in `test_dashboard.py` Task 3 ✅
- `make_server(host, port, db_path)` defined Task 3 → used in test and `main()` ✅
