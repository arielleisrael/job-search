#!/usr/bin/env python3
"""
Arielle Israel — Job Application Auto-Filler v1
Uses Playwright to open job application pages, pre-fill your info,
attach your resume, and pause for your final review before YOU submit.

Supports: LinkedIn Easy Apply, Indeed, Greenhouse, Lever, and generic forms.

Usage:
  python3 autofiller.py --jobs results/jobs_2026-08-06.csv   # run from today's job results
  python3 autofiller.py --url "https://job-url-here"         # single job URL
  python3 autofiller.py --jobs results/jobs_2026-08-06.csv --tier "STRONG"  # only strong fits
  python3 autofiller.py --jobs results/jobs_2026-08-06.csv --limit 20       # cap at 20 roles

Setup (one time):
  pip install playwright
  playwright install chromium
"""

import sys
import csv
import time
import argparse
import subprocess
import sqlite3
from pathlib import Path

# ── Auto-install Playwright ────────────────────────────────────────────────
def ensure_playwright():
    try:
        import playwright
    except ImportError:
        print("Installing Playwright...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "-q"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        print("✅ Playwright installed\n")

ensure_playwright()

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

DB_PATH = Path(__file__).parent.parent / "applied_jobs.db"


def update_job_status(url, status):
    """Mark a job applied or skipped in the shared DB so the agent won't resurface it."""
    if not url or not DB_PATH.exists():
        return
    try:
        today = time.strftime("%Y-%m-%d")
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE jobs SET status=?, date_acted=? WHERE url=?",
            (status, today, url)
        )
        # Insert if URL wasn't in a prior agent run (e.g. manually supplied URL)
        conn.execute(
            "INSERT OR IGNORE INTO jobs (url, status, date_acted) VALUES (?, ?, ?)",
            (url, status, today)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  ⚠ DB update failed: {e}", file=sys.stderr)


def write_session_log(log_path, entries):
    """
    Write session log entries to a CSV file.
    entries: list of dicts with keys: timestamp, action, title, company, source, score, url
    Creates logs/ directory if it doesn't exist.
    """
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["timestamp", "action", "title", "company", "source", "score", "url"]
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry)


def _log_entry(job, action):
    """Build a session-log dict for one job action."""
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "action":    action,
        "title":     job.get("title", ""),
        "company":   job.get("company", ""),
        "source":    job.get("source", ""),
        "score":     job.get("score", ""),
        "url":       job.get("url", ""),
    }


# ── YOUR PROFILE ───────────────────────────────────────────────────────────
# Update these once. They feed every form field automatically.
PROFILE = {
    # Personal
    "first_name":    "Arielle",
    "last_name":     "Israel",
    "full_name":     "Arielle Israel",
    "email":         "arielleisrael3@gmail.com",
    "phone":         "",           # ← Add your phone number
    "location":      "Austin, TX",
    "city":          "Austin",
    "state":         "TX",
    "zip":           "",           # ← Add your zip code

    # Professional
    "linkedin_url":  "",           # ← Add your LinkedIn URL
    "github_url":    "",           # ← Add if you have one
    "portfolio_url": "",           # ← Add if applicable
    "years_exp":     "17",
    "current_title": "Lead Software Development Engineer in Test",
    "salary_expectation": "115000",  # mid of your range

    # Resume — IMPORTANT: update this path to where your resume PDF lives
    "resume_path":   str(Path.home() / "job-search" / "resume.pdf"),

    # Work authorization
    "authorized":    "Yes",        # Are you authorized to work in the US?
    "sponsorship":   "No",         # Do you require sponsorship?
    "remote_only":   "Yes",

    # Cover note template — used when a short text field asks for one
    "cover_note": (
        "I'm a Quality Engineering leader with 17+ years of experience building "
        "automation-first QE strategies across web and mobile platforms. I've led "
        "teams using Cypress, Playwright, and Appium to achieve 60%+ gains in test "
        "coverage and significant reductions in production defects. I'm excited about "
        "this role and would love to bring that experience to your team."
    ),
}

# ── FIELD MATCHERS ─────────────────────────────────────────────────────────
# Maps common form field labels/names/ids → your profile values.
# Playwright will try to find these on any form page.

FIELD_MAP = [
    # Name
    (["first name", "first_name", "fname", "given name"],       PROFILE["first_name"]),
    (["last name", "last_name", "lname", "surname", "family"],  PROFILE["last_name"]),
    (["full name", "name", "your name", "applicant name"],      PROFILE["full_name"]),

    # Contact
    (["email", "e-mail", "email address"],                      PROFILE["email"]),
    (["phone", "mobile", "cell", "telephone", "phone number"],  PROFILE["phone"]),

    # Location
    (["city"],                                                   PROFILE["city"]),
    (["state"],                                                  PROFILE["state"]),
    (["zip", "postal", "postal code"],                           PROFILE["zip"]),
    (["location", "address", "current location"],               PROFILE["location"]),

    # Professional
    (["linkedin", "linkedin url", "linkedin profile"],          PROFILE["linkedin_url"]),
    (["github", "github url"],                                   PROFILE["github_url"]),
    (["portfolio", "website", "personal site"],                  PROFILE["portfolio_url"]),
    (["years of experience", "years experience", "experience"],  PROFILE["years_exp"]),
    (["current title", "current role", "job title"],             PROFILE["current_title"]),
    (["salary", "expected salary", "desired salary",
      "compensation", "expected compensation"],                   PROFILE["salary_expectation"]),

    # Work auth
    (["authorized", "work authorization", "eligible to work",
      "legally authorized"],                                     PROFILE["authorized"]),
    (["sponsorship", "visa sponsorship", "require sponsorship"], PROFILE["sponsorship"]),

    # Cover
    (["cover letter", "cover note", "why do you want",
      "why are you interested", "tell us about yourself"],       PROFILE["cover_note"]),
]

# ── YES/NO RADIO PATTERNS ──────────────────────────────────────────────────
# For radio buttons/dropdowns: maps label patterns → what to select
YES_NO_MAP = [
    (["authorized", "work in the us", "eligible to work"],   "Yes"),
    (["sponsorship", "require sponsorship", "need visa"],     "No"),
    (["remote", "work remotely"],                             "Yes"),
    (["relocate", "willing to relocate"],                     "No"),
]

# ── UTILITIES ──────────────────────────────────────────────────────────────
def log(msg, emoji=""):
    print(f"  {emoji}  {msg}" if emoji else f"  {msg}")


def safe_fill(page, selector, value, label="field"):
    """Try to fill a field, skip gracefully if not found or empty value."""
    if not value:
        return False
    try:
        el = page.locator(selector).first
        if el.count() and el.is_visible(timeout=2000):
            el.fill(str(value))
            return True
    except Exception:
        pass
    return False


def find_and_fill_by_label(page, label_texts, value):
    """
    Find an input associated with any of the given label texts and fill it.
    Tries: aria-label, placeholder, label[for], nearby label text.
    """
    if not value:
        return False
    for text in label_texts:
        selectors = [
            f'input[aria-label*="{text}" i]',
            f'input[placeholder*="{text}" i]',
            f'textarea[aria-label*="{text}" i]',
            f'textarea[placeholder*="{text}" i]',
            f'input[name*="{text.replace(" ","_")}" i]',
            f'input[id*="{text.replace(" ","_")}" i]',
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.count() and el.is_visible(timeout=1500):
                    tag = el.evaluate("el => el.tagName.toLowerCase()")
                    if tag == "textarea":
                        el.fill(str(value))
                    else:
                        el.fill(str(value))
                    log(f"Filled '{text}' field", "✓")
                    return True
            except Exception:
                continue

        # Try finding by nearby label text
        try:
            label_el = page.get_by_text(text, exact=False).first
            if label_el.count():
                # Get the associated input via for= attribute or next sibling
                for_attr = label_el.evaluate(
                    "el => el.htmlFor || el.getAttribute('for') || ''"
                )
                if for_attr:
                    inp = page.locator(f"#{for_attr}").first
                    if inp.count() and inp.is_visible(timeout=1500):
                        inp.fill(str(value))
                        log(f"Filled '{text}' via label", "✓")
                        return True
        except Exception:
            pass
    return False


def attach_resume(page, resume_path):
    """Find a file input and attach the resume."""
    path = Path(resume_path)
    if not path.exists():
        log(f"⚠ Resume not found at {resume_path} — skipping attachment", "!")
        log("  Update PROFILE['resume_path'] to your actual PDF path", "!")
        return False

    file_selectors = [
        'input[type="file"]',
        'input[accept*="pdf"]',
        'input[accept*=".pdf"]',
        'input[name*="resume" i]',
        'input[id*="resume" i]',
        'input[data-testid*="resume" i]',
    ]
    for sel in file_selectors:
        try:
            el = page.locator(sel).first
            if el.count():
                el.set_input_files(str(path))
                log(f"Resume attached: {path.name}", "📎")
                return True
        except Exception:
            continue
    log("Could not find file upload field — attach resume manually", "!")
    return False


def handle_yes_no_radios(page):
    """Try to select appropriate radio buttons / dropdowns for common yes/no questions."""
    for label_patterns, answer in YES_NO_MAP:
        for pattern in label_patterns:
            try:
                # Radio buttons
                radios = page.locator(f'input[type="radio"]')
                count = radios.count()
                for i in range(count):
                    radio = radios.nth(i)
                    label_text = radio.evaluate(
                        "el => { "
                        "  const id = el.id; "
                        "  const label = document.querySelector(`label[for='${id}']`); "
                        "  return label ? label.innerText : el.value || ''; "
                        "}"
                    ).lower()
                    nearby_text = ""
                    try:
                        nearby_text = radio.evaluate(
                            "el => el.closest('div,fieldset,li')?.innerText || ''"
                        ).lower()
                    except Exception:
                        pass
                    full_context = label_text + " " + nearby_text
                    if pattern.lower() in full_context and answer.lower() in label_text:
                        radio.check()
                        log(f"Selected '{answer}' for '{pattern}'", "✓")
                        break
            except Exception:
                continue


def scroll_and_fill_all(page):
    """Walk through FIELD_MAP and fill whatever fields are on the page."""
    filled = 0
    for label_patterns, value in FIELD_MAP:
        if find_and_fill_by_label(page, label_patterns, value):
            filled += 1
            time.sleep(0.3)
    handle_yes_no_radios(page)
    attach_resume(page, PROFILE["resume_path"])
    return filled


def auto_advance_pages(page, max_steps=8):
    """
    After filling a form page, detect and click Next/Continue if present.
    Stops when no Next button is found (final page) or max_steps is reached.
    Never clicks Submit, Apply, or Send buttons — those stay for the user.
    Returns the number of pages advanced (0 = already on final page).
    """
    NEXT_SELECTORS = [
        'button:has-text("Next")',
        'button:has-text("Continue")',
        'button:has-text("Next Step")',
        'button:has-text("Save and Continue")',
        'input[type="submit"][value*="Next" i]',
        'input[type="submit"][value*="Continue" i]',
    ]
    STOP_WORDS = ["submit", "apply", "send application", "review application", "finish"]

    steps = 0
    for _ in range(max_steps):
        next_btn = None
        for selector in NEXT_SELECTORS:
            try:
                el = page.locator(selector).first
                if el.count() and el.is_visible(timeout=2000):
                    # Check stop words against the button's text content or value
                    try:
                        btn_text = el.evaluate(
                            "el => (el.textContent || el.value || '').toLowerCase().trim()"
                        )
                    except Exception:
                        btn_text = ""
                    if any(sw in btn_text for sw in STOP_WORDS):
                        return steps
                    next_btn = el
                    break
            except Exception:
                continue

        if next_btn is None:
            break

        prev_url = page.url

        try:
            next_btn.click()
        except Exception:
            break  # failed to click, treat current page as final

        page.wait_for_timeout(1800)

        if page.url == prev_url:
            break  # stuck on the same page (validation error etc.) — treat as final

        scroll_and_fill_all(page)
        steps += 1
        log(f"Auto-advanced to page {steps + 1}", "➡")

    return steps


# ── PLATFORM-SPECIFIC HANDLERS ─────────────────────────────────────────────

def handle_linkedin(page, url):
    """LinkedIn Easy Apply flow."""
    log("LinkedIn Easy Apply detected", "🔗")
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # Click Easy Apply button
    try:
        easy_apply_btn = page.locator(
            'button:has-text("Easy Apply"), '
            'button[data-control-name="jobdetails_topcard_inapply"]'
        ).first
        if easy_apply_btn.count() and easy_apply_btn.is_visible():
            easy_apply_btn.click()
            page.wait_for_timeout(1500)
            log("Clicked Easy Apply", "✓")
    except Exception:
        log("Could not click Easy Apply — may need to be on the job page directly", "!")

    # Fill modal form fields
    scroll_and_fill_all(page)
    log("Fields pre-filled. Review the form, then click Submit.", "👀")


def handle_greenhouse(page, url):
    """Greenhouse application form."""
    log("Greenhouse board detected", "🌱")
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    scroll_and_fill_all(page)
    auto_advance_pages(page)
    log("Fields pre-filled. Review and submit when ready.", "👀")


def handle_lever(page, url):
    """Lever application form."""
    log("Lever board detected", "⚡")
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    scroll_and_fill_all(page)
    auto_advance_pages(page)
    log("Fields pre-filled. Review and submit when ready.", "👀")


def handle_indeed(page, url):
    """Indeed application — navigates to apply page."""
    log("Indeed detected", "🔍")
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # Try to find and click Apply button
    try:
        apply_btn = page.locator(
            'button:has-text("Apply now"), '
            'a:has-text("Apply now"), '
            'button:has-text("Apply")'
        ).first
        if apply_btn.count() and apply_btn.is_visible():
            apply_btn.click()
            page.wait_for_timeout(2000)
            log("Clicked Apply", "✓")
    except Exception:
        pass

    scroll_and_fill_all(page)
    auto_advance_pages(page)
    log("Fields pre-filled. Review and submit when ready.", "👀")


def handle_generic(page, url):
    """Generic fallback for any other job board."""
    log("Generic form handler", "📋")
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # Look for an Apply button to click first
    try:
        apply_btn = page.locator(
            'a:has-text("Apply"), button:has-text("Apply"), '
            'a:has-text("Apply Now"), button:has-text("Apply Now")'
        ).first
        if apply_btn.count() and apply_btn.is_visible(timeout=3000):
            apply_btn.click()
            page.wait_for_timeout(2000)
            log("Clicked Apply button", "✓")
    except Exception:
        pass

    scroll_and_fill_all(page)
    auto_advance_pages(page)
    log("Fields pre-filled. Review and submit when ready.", "👀")


def detect_platform(url):
    url_lower = url.lower()
    if "linkedin.com" in url_lower:      return "linkedin"
    if "greenhouse.io" in url_lower:     return "greenhouse"
    if "lever.co" in url_lower:          return "lever"
    if "indeed.com" in url_lower:        return "indeed"
    return "generic"


HANDLERS = {
    "linkedin":   handle_linkedin,
    "greenhouse": handle_greenhouse,
    "lever":      handle_lever,
    "indeed":     handle_indeed,
    "generic":    handle_generic,
}


# ── MAIN APPLICATION LOOP ─────────────────────────────────────────────────
def get_chrome_profile_path():
    """Find the user's real Chrome profile on Mac/Windows/Linux."""
    import platform, os
    system = platform.system()
    home = Path.home()
    candidates = []
    if system == "Darwin":   # Mac
        candidates = [
            home / "Library/Application Support/Google/Chrome/Default",
            home / "Library/Application Support/Google/Chrome",
            home / "Library/Application Support/Chromium/Default",
        ]
    elif system == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        candidates = [
            local / "Google/Chrome/User Data/Default",
            local / "Google/Chrome/User Data",
        ]
    else:  # Linux
        candidates = [
            home / ".config/google-chrome/Default",
            home / ".config/chromium/Default",
        ]
    for p in candidates:
        if p.exists():
            # Playwright wants the parent of "Default", not "Default" itself
            return str(p.parent) if p.name == "Default" else str(p)
    return None


def _close_context(context):
    """Close a browser context and its backing browser if one was launched for it."""
    if context is None:
        return
    browser = context.browser  # None for persistent contexts
    try:
        context.close()
    except Exception:
        pass
    if browser:
        try:
            browser.close()
        except Exception:
            pass


def _open_shared_context(playwright, headless=False):
    """
    Open a single browser context (persistent Chrome profile if available, fresh
    Chromium otherwise). Returns the context, or None on failure. Caller is
    responsible for closing via _close_context().
    """
    chrome_profile = get_chrome_profile_path()

    if chrome_profile:
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=chrome_profile,
                headless=headless,
                slow_mo=80,
                channel="chrome",          # use installed Chrome, not bundled Chromium
                args=["--no-first-run", "--no-default-browser-check"],
                viewport={"width": 1280, "height": 900},
            )
            log("Using your Chrome profile (auth sessions inherited)", "✓")
            return context
        except Exception as e:
            log(f"Could not load Chrome profile ({e}) — using fresh browser", "!")

    # Fallback: launch a plain Chromium browser
    try:
        browser = playwright.chromium.launch(headless=headless, slow_mo=80)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        log("Using fresh browser — you may need to log in to LinkedIn/Indeed manually", "!")
        return context
    except Exception as e:
        log(f"Failed to launch browser: {e}", "!")
        return None


def _prefill_page(page, job_info):
    """
    Navigate to job_info['url'] and pre-fill the form on an already-open page.
    Prints the job header and calls the appropriate platform handler.
    """
    url = job_info.get("url", "") if isinstance(job_info, dict) else str(job_info)

    if isinstance(job_info, dict) and (job_info.get("title") or job_info.get("company")):
        print(f"\n{'─'*60}")
        print(f"  {job_info.get('title', 'Role')} @ {job_info.get('company', '')}")
        print(f"  Score: {job_info.get('score', '?')}/100  |  {job_info.get('source', '')}")
        print(f"  {url}")
        print(f"{'─'*60}")

    platform = detect_platform(url)
    handler = HANDLERS[platform]
    handler(page, url)


def run_application_prefill(playwright, job_info, headless=False):
    """
    Open a browser context for job_info['url'], pre-fill the form.
    Returns the (context, page, url) tuple — caller is responsible for close.
    Returns (None, None, url) on failure.
    """
    url = job_info.get("url", "") if isinstance(job_info, dict) else str(job_info)

    context = _open_shared_context(playwright, headless)
    if context is None:
        return (None, None, url)

    try:
        page = context.new_page()
        _prefill_page(page, job_info)
        return (context, page, url)
    except Exception as e:
        log(f"Error pre-filling application: {e}", "!")
        _close_context(context)
        return (None, None, url)


def run_application(playwright, url, job_info=None, headless=False):
    """Open one job application, pre-fill, and wait for user to submit."""
    if job_info is None:
        job_info = {"url": url, "title": "Role", "company": "", "score": "?", "source": ""}
    else:
        job_info = dict(job_info)
        job_info.setdefault("url", url)

    context, page, url = run_application_prefill(playwright, job_info, headless)

    if context is None:
        log("Failed to open application — browser error, will retry next run", "!")
        return None  # not a user action; do not write to DB

    # ── Hand control to user ───────────────────────────────────────────────
    print()
    print("  ┌─────────────────────────────────────────────────┐")
    print("  │  👆  YOUR TURN — review the form and submit     │")
    print("  │                                                 │")
    print("  │  When done, come back here and press ENTER      │")
    print("  │  to move to the next application.              │")
    print("  │                                                 │")
    print("  │  Type 's' + ENTER to skip this one.            │")
    print("  │  Type 'q' + ENTER to quit the session.         │")
    print("  └─────────────────────────────────────────────────┘")

    try:
        response = input("  ▶ ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        response = "q"

    _close_context(context)
    return response  # "", "s" (skip), or "q" (quit)


def run_batch_session(playwright, jobs, batch_size=5, headless=False, log_entries=None):
    """
    Open up to `batch_size` jobs simultaneously in a shared browser context,
    pre-fill each as a separate page, then let the user cycle through and submit.
    Returns (applied, skipped).
    If log_entries list is provided, batch appends action dicts to it in-place.
    """
    applied = 0
    skipped = 0
    total_batches = (len(jobs) + batch_size - 1) // batch_size

    for batch_num, chunk_start in enumerate(range(0, len(jobs), batch_size), 1):
        chunk = jobs[chunk_start: chunk_start + batch_size]
        n = len(chunk)

        # ── Open ONE shared context for the whole chunk ────────────────────
        # A single launch_persistent_context call avoids the Chrome profile
        # filesystem lock that would prevent a second context from inheriting auth.
        print(f"\n  Opening {n} application(s) in batch {batch_num} of {total_batches}...")
        shared_context = _open_shared_context(playwright, headless)
        if shared_context is None:
            log("Could not open browser for this batch — skipping all jobs in chunk", "!")
            continue

        # ── Pre-fill each job as a new page inside the shared context ─────
        open_tabs = []  # list of (page_or_None, url, job)
        # Persistent contexts open with one about:blank page already.  Reuse it
        # for the first job so Chrome shows it as tab 1, not tab 2.
        pages_pool = list(shared_context.pages)

        for job in chunk:
            tab_url = job.get("url", "")
            if not tab_url:
                continue
            print(f"\n  Pre-filling: {job.get('title', 'Role')} @ {job.get('company', '')}...")
            try:
                if pages_pool:
                    page = pages_pool.pop(0)
                else:
                    page = shared_context.new_page()
                _prefill_page(page, job)
                open_tabs.append((page, tab_url, job))
            except Exception as e:
                log(f"Error pre-filling {tab_url}: {e}", "!")
                open_tabs.append((None, tab_url, job))

        if not open_tabs:
            _close_context(shared_context)
            continue

        # ── Print batch summary table ──────────────────────────────────────
        W = 54  # inner width of the box
        n_open = len(open_tabs)
        header_text = (
            f"  Batch {batch_num} of {total_batches}"
            f"  —  {n_open} tab{'s' if n_open != 1 else ''} pre-filled and waiting  "
        )
        print(f"\n  ┌{'─' * W}┐")
        print(f"  │{header_text[:W].ljust(W)}│")
        print(f"  ├{'─' * W}┤")

        for tab_idx, (pg, tab_url, job) in enumerate(open_tabs, 1):
            title = (job.get("title") or "Role")[:24]
            company = (job.get("company") or "")[:14]
            pname = detect_platform(tab_url).capitalize()
            bracket = f"[{pname}]"
            left = f"  Tab {tab_idx}: {title} @ {company}"
            gap = max(1, W - len(left) - len(bracket))
            row = (left + " " * gap + bracket)[:W].ljust(W)
            print(f"  │{row}│")

        print(f"  └{'─' * W}┘")
        print(f"\n  Switch to Tab 1 in your browser, review and submit, then come back here.")

        # ── Process each tab in sequence; close each page after user action ─
        quit_session = False
        for i, (page, tab_url, job) in enumerate(open_tabs):
            tab_idx = i + 1
            title = (job.get("title") or "Role")
            company = (job.get("company") or "")
            tab_label = f"{title} @ {company}" if company else title

            if page is None:
                print(f"\n  Tab {tab_idx} ({tab_label}) — failed to open, skipping.")
                continue

            print(f"\n  Tab {tab_idx} ({tab_label})")
            print(
                f"  Press ENTER when submitted, 's' to skip, 'q' to quit: ",
                end="", flush=True,
            )
            try:
                response = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                response = "q"

            if response == "q":
                try:
                    page.close()
                except Exception:
                    pass
                for remaining_page, _, _ in open_tabs[i + 1:]:
                    if remaining_page is not None:
                        try:
                            remaining_page.close()
                        except Exception:
                            pass
                quit_session = True
                break
            elif response == "s":
                update_job_status(tab_url, "skipped")
                skipped += 1
                if log_entries is not None:
                    log_entries.append(_log_entry(job, "skipped"))
                print("  Skipped.")
            else:
                update_job_status(tab_url, "applied")
                applied += 1
                if log_entries is not None:
                    log_entries.append(_log_entry(job, "applied"))
                print(f"  ✅ Application {applied} submitted.")

            try:
                page.close()
            except Exception:
                pass

        # Close the shared context after all pages in this chunk are done
        _close_context(shared_context)

        if quit_session:
            break

    return (applied, skipped)


def load_jobs_from_csv(csv_path, tier_filter=None, limit=None):
    """Load job URLs from the agent's output CSV, optionally filtering by tier."""
    jobs = []
    path = Path(csv_path)
    if not path.exists():
        print(f"❌ CSV not found: {csv_path}")
        sys.exit(1)

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if tier_filter:
                row_tier = row.get("tier", "").upper()
                if tier_filter.upper() not in row_tier:
                    continue
            if row.get("url"):
                jobs.append(row)

    if limit:
        jobs = jobs[:limit]
    return jobs


def main():
    parser = argparse.ArgumentParser(description="Job Application Auto-Filler")
    parser.add_argument("--jobs",  help="Path to jobs CSV from the search agent")
    parser.add_argument("--url",   help="Single job URL to apply to")
    parser.add_argument("--tier",  default=None,
                        help='Filter CSV by tier: "STRONG", "GOOD", or "POSSIBLE"')
    parser.add_argument("--limit", type=int, default=None,
                        help="Max number of applications to run")
    parser.add_argument("--headless", action="store_true",
                        help="Run browser in headless mode (not recommended)")
    parser.add_argument("--batch", type=int, default=5, metavar="N",
                        help="Open N applications simultaneously (default: 5; 1 = sequential mode)")
    args = parser.parse_args()

    if not 1 <= args.batch <= 10:
        parser.error("--batch must be between 1 and 10")

    if not args.jobs and not args.url:
        parser.print_help()
        sys.exit(1)

    # Build job list
    if args.url:
        jobs = [{"url": args.url, "title": "Role", "company": "", "score": "?", "source": ""}]
    else:
        jobs = load_jobs_from_csv(args.jobs, tier_filter=args.tier, limit=args.limit)

    if not jobs:
        print("❌ No jobs found matching your filters.")
        sys.exit(0)

    print(f"\n🚀 Job Application Auto-Filler — Arielle Israel")
    print(f"   {len(jobs)} application(s) queued")
    if args.tier:
        print(f"   Filter: {args.tier} fit only")
    mode_label = f"Batch (size {args.batch})" if args.batch > 1 else "Sequential"
    print(f"   Mode: {mode_label}")
    print(f"\n   ⚠  You will review and submit each one yourself.")
    print(f"   ⚠  Update PROFILE['resume_path'] before running if needed.")
    print(f"\n   Resume: {PROFILE['resume_path']}")
    resume_exists = Path(PROFILE["resume_path"]).exists()
    if not resume_exists:
        print(f"   ⚠  Resume file not found at that path — update it in the script!")
    print()
    input("   Press ENTER to begin, or Ctrl+C to cancel...\n")

    session_start = time.time()
    log_entries = []
    log_path = (
        Path(__file__).parent.parent
        / "logs"
        / f"session_{time.strftime('%Y-%m-%d_%H%M', time.localtime(session_start))}.csv"
    )

    applied = 0
    skipped = 0

    with sync_playwright() as playwright:
        if args.batch > 1:
            app, skip = run_batch_session(
                playwright, jobs, batch_size=args.batch, headless=args.headless,
                log_entries=log_entries,
            )
            applied += app
            skipped += skip
        else:
            for i, job in enumerate(jobs, 1):
                url = job.get("url", "")
                if not url:
                    continue

                print(f"\n[{i}/{len(jobs)}] Opening application...")
                result = run_application(playwright, url, job_info=job, headless=args.headless)

                if result is None:
                    continue  # browser error — job stays pending, no DB write
                elif result == "q":
                    print("\n  Session ended by user.")
                    break
                elif result == "s":
                    skipped += 1
                    update_job_status(url, "skipped")
                    log_entries.append(_log_entry(job, "skipped"))
                    print("  Skipped.")
                else:
                    applied += 1
                    update_job_status(url, "applied")
                    log_entries.append(_log_entry(job, "applied"))
                    print(f"  ✅ Application {applied} submitted.")

                # Brief pause between applications
                if i < len(jobs) and result not in ("q",):
                    print(f"\n  Pausing 3 seconds before next application...")
                    time.sleep(3)

    session_end = time.time()
    write_session_log(log_path, log_entries)
    total_reviewed = applied + skipped
    log_rel = f"logs/{log_path.name}"

    print(f"\n{'='*60}")
    print(f"  Session complete!")
    print(f"  ✅ Submitted: {applied}")
    print(f"  ⏭  Skipped:   {skipped}")
    print(f"  📋 Session log: {log_rel}")
    print(f"     Applied: {applied} | Skipped: {skipped} | Total reviewed: {total_reviewed}")
    if total_reviewed > 0:
        avg_secs = (session_end - session_start) / total_reviewed
        avg_min = int(avg_secs // 60)
        avg_sec = int(avg_secs % 60)
        print(f"     Avg time per application: {avg_min}m {avg_sec}s")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
