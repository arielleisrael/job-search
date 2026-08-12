# Phase 3 Design — Cover Notes, Resume Variants, Dashboard

**Date:** 2026-08-11  
**Status:** Approved  
**Scope:** Quality improvements layered onto the existing Phase 1/2 job search automation system

---

## Overview

Phase 3 adds three features that improve application quality and pipeline visibility without changing any Phase 1/2 behavior:

1. **Claude API cover notes** — per-job tailored 3-sentence cover note generated at autofill time
2. **Resume variant switching** — automatic PDF selection based on job title; manual override flag
3. **Pipeline dashboard** — local web server with kanban-style view and in-page status updates

---

## Architecture

```
job_search_agent_v2.py     (unchanged)
applied_jobs.db            (status values expanded; no new columns)
autofiller/autofiller.py   (cover note + resume variant injected per job)
dashboard/dashboard.py     (new: stdlib http.server + inline HTML)
```

No new Python package dependencies beyond `anthropic` (for cover notes). Dashboard uses stdlib only.

---

## Feature 1: Claude API Cover Notes

### What it does
Before filling each application form, scrape the job page text and call the Claude API to generate a 3-sentence tailored cover note. Falls back to the static `PROFILE["cover_note"]` on any API failure.

### Where it runs
Inside `autofiller.py`, after the autofiller navigates to the job URL but before `scroll_and_fill_all` is called. The page is already open in Playwright, so no extra navigation is needed.

### New function: `pick_cover_note(page, job) -> str`

1. Call `page.inner_text("body")`, trim to first 3000 characters
2. Call `anthropic.Anthropic().messages.create()` with model `claude-haiku-4-5-20251001`:

```
System: You are writing a cover note for a job application. Write exactly 3 sentences.
Tone: confident, specific, no filler phrases. Output only the 3 sentences, no preamble.

User: Candidate: Arielle Israel, QE leader, 17+ years, specializes in Playwright/Cypress/Appium,
web + mobile automation, CI/CD, team leadership.
Job title: {title} at {company}.
Job description excerpt: {text}
```

3. Return `response.content[0].text.strip()`
4. On any exception: print one-line warning, return `PROFILE["cover_note"]`

### Integration
The returned string is passed directly into the `scroll_and_fill_all` call as a local override — `PROFILE["cover_note"]` is never mutated, so other jobs in the same batch are unaffected.

### Cost and latency
~$0.001/call (Haiku). 100 apps/day ≈ $0.10/day. Adds ~1–2 seconds per job.

### Environment
Reads `ANTHROPIC_API_KEY` from environment. If the key is missing, prints a startup warning and skips cover note generation for the session (falls back to static note for all jobs).

---

## Feature 2: Resume Variant Switching

### What it does
Automatically selects one of three resume PDFs based on job title keywords. An optional CLI flag overrides auto-detection for the entire batch.

### New function: `pick_resume(title: str) -> str`

Pure function, no I/O:

```python
RESUME_VARIANTS = {
    "manager":   "Resume-QE-Manager-ArielleIsrael.pdf",
    "director":  "Resume-QE-Manager-ArielleIsrael.pdf",
    "lead":      "Resume-Lead-SDET-ArielleIsrael.pdf",
    "staff":     "Resume-Lead-SDET-ArielleIsrael.pdf",
    "principal": "Resume-Lead-SDET-ArielleIsrael.pdf",
}
RESUME_DEFAULT = "Resume-Senior-Quality-Engineer-ArielleIsrael.pdf"
RESUME_BASE    = Path.home() / "job-search"

def pick_resume(title: str) -> str:
    t = title.lower()
    for keyword, filename in RESUME_VARIANTS.items():
        if keyword in t:
            return str(RESUME_BASE / filename)
    return str(RESUME_BASE / RESUME_DEFAULT)
```

### CLI flag
`--resume ic|manager|lead` forces a specific PDF for the whole batch session, bypassing `pick_resume`. Validated at startup with `parser.error()` if an unrecognized value is passed.

Map: `ic` → default IC PDF, `manager` → manager PDF, `lead` → lead/staff PDF.

### Startup validation
At startup, before any tabs open, check all three variant PDFs exist. Print a warning for any missing file (do not abort — autofiller falls back to whatever file is valid).

### Integration
`pick_resume(job["title"])` (or the forced variant) is passed into each job's fill pass alongside the cover note — `PROFILE["resume_path"]` is never mutated.

---

## Feature 3: Pipeline Dashboard

### What it does
A local web server at `localhost:8787` serving a dashboard built fresh from `applied_jobs.db` on each page load. Status update buttons POST back to the server, which writes the DB and redirects.

### Running it
```bash
python3 dashboard/dashboard.py
# Opens http://localhost:8787 in the default browser automatically
# Ctrl-C to stop
```

### DB status values (expanded)
Existing: `new`, `applied`, `skipped`  
New: `responded`, `interviewed`, `offered`, `rejected`

No schema changes — these are just additional valid strings for the existing `status` column.

### Page layout

**Header stats:**
- Total applied
- Response rate: `(responded + interviewed + offered) / applied × 100%`
- Interview rate: `(interviewed + offered) / applied × 100%`

**Kanban columns (left to right):** Applied → Responded → Interviewed → Offered  
`Rejected` is a terminal state shown as a collapsed count at the bottom, not a column.

**Each card shows:** company, title, date applied (date_acted), score/tier badge

**Per-card status buttons:**
- Applied card: `[Responded] [Rejected]`
- Responded card: `[Interviewed] [Rejected]`
- Interviewed card: `[Offered] [Rejected]`
- Offered/Rejected: no buttons (terminal states)

**Bottom table:** application count by source (LinkedIn, Greenhouse, Ashby, etc.)

### Server endpoints
- `GET /` — query DB, render full HTML inline, return 200
- `POST /update` — body: `url=<encoded>&status=<status>` — write DB, return 302 to `/`

### Security
Binds to `127.0.0.1` only. No auth needed (local-only).

### Dependencies
stdlib only: `http.server`, `urllib.parse`, `sqlite3`, `webbrowser`, `threading`

---

## File changes summary

| File | Change |
|------|--------|
| `autofiller/autofiller.py` | Add `pick_cover_note()`, `pick_resume()`, `RESUME_VARIANTS`; add `--resume` flag; startup API key check + resume file check |
| `dashboard/dashboard.py` | New file — stdlib HTTP server + inline HTML dashboard |
| `applied_jobs.db` | No schema change — new status values used by existing `status` column |

---

## Out of scope

- Auto-submitting applications (user always reviews and submits)
- Storing generated cover notes in the DB
- Email/calendar integration for tracking responses automatically
- Any external hosting of the dashboard
