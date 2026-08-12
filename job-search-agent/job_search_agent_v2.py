#!/usr/bin/env python3
"""
Arielle Israel — QE Job Search Agent v2
Searches APIs + scrapes LinkedIn, Indeed, We Work Remotely, Jobicy, Remote.co,
and direct Greenhouse/Lever boards for QE/SDET/Lead/Manager remote roles.

Usage:
  python3 job_search_agent_v2.py              # run search, print results
  python3 job_search_agent_v2.py --save       # save to CSV + markdown
  python3 job_search_agent_v2.py --since 7    # jobs posted in last N days (default: 3)
  python3 job_search_agent_v2.py --min-score 40  # raise fit threshold

Dependencies (auto-installed on first run):
  pip install requests beautifulsoup4 lxml
"""

import sys
import subprocess

# Auto-install dependencies
def ensure_deps():
    needed = {"requests": "requests", "bs4": "beautifulsoup4", "lxml": "lxml"}
    for imp, pkg in needed.items():
        try:
            __import__(imp)
        except ImportError:
            print(f"  Installing {pkg}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--break-system-packages", "-q"])

ensure_deps()

import re
import csv
import json
import time
import random
import argparse
import requests
from datetime import datetime, timedelta
from pathlib import Path
from bs4 import BeautifulSoup
import sqlite3

# ─── PROFILE ─────────────────────────────────────────────────────────────────
PROFILE = {
    "name": "Arielle Israel",
    "target_titles": [
        "Senior Quality Engineer",
        "Quality Engineering Lead",
        "QE Lead",
        "Senior QE",
        "SDET Lead",
        "Lead SDET",
        "Software Development Engineer in Test",
        "Senior SDET",
        "Quality Engineering Manager",
        "QE Manager",
        "Staff Quality Engineer",
        "Principal Quality Engineer",
    ],
    "search_queries": [
        "senior quality engineer remote",
        "SDET lead remote",
        "quality engineering manager remote",
        "lead SDET remote",
        "software development engineer in test remote",
        "QE lead remote",
        "senior test automation engineer remote",
        "quality engineering lead remote",
    ],
    "must_be_remote": True,
    "salary_min": 100_000,
    "salary_max": 130_000,
    "top_skills": [
        "Cypress", "Playwright", "Appium", "JavaScript", "test automation",
        "mobile testing", "CI/CD", "GitHub Actions", "Jenkins", "Selenium",
        "WebdriverIO", "pytest", "API testing", "SDET", "quality engineering",
    ],
    "years_experience": 17,
    "seniority_keywords": ["senior", "lead", "manager", "staff", "principal", "head of"],
    "avoid_keywords": [
        "on-site only", "onsite only", "must be local", "no remote",
        "junior", "entry level", "intern", "0-2 years", "1-2 years",
        # Manufacturing / physical QE roles — not software
        "plant quality", "manufacturing quality", "assembly plant",
        "shop floor", "production quality", "supplier quality",
        "incoming inspection", "iso 9001", "iatf 16949", "as9100",
        "cmm", "metrology", "welding", "stamping", "machining",
    ],
    # Roles must be open to US-based applicants.
    # Listings containing these without US signals get filtered out hard.
    "non_us_signals": [
        "uk only", "united kingdom only", "eu only", "europe only",
        "canada only", "australia only", "india only", "latam only",
        "emea only", "apac only", "latin america only", "mexico only",
        "costa rica only", "outside the us", "not available in the us",
        "not open to us", "must be based in", "must reside in", "must live in",
        "not eligible to work in the us", "excluding the us", "no us applicants",
    ],
    # At least one of these must appear, OR location/description must be silent
    # (we give benefit of the doubt unless a non-US signal is explicit)
    "us_positive_signals": [
        "united states", "u.s.", "us only", "us-based", "us residents",
        "must be us", "work in the us", "authorized to work in the us",
        "remote us", "remote - us", "remote (us)", "remote, us",
        "anywhere in the us", "all 50 states", "conus",
    ],
    "preferred_company_signals": [
        "series c", "series d", "series e", "growth stage",
        "saas", "fintech", "healthtech", "b2b",
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ─── APPLIED-JOBS DATABASE ────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent.parent / "applied_jobs.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            url        TEXT PRIMARY KEY,
            title      TEXT,
            company    TEXT,
            source     TEXT,
            score      INTEGER,
            tier       TEXT,
            status     TEXT DEFAULT 'new',
            date_seen  TEXT DEFAULT (date('now')),
            date_acted TEXT
        )
    """)
    conn.commit()
    conn.close()


def load_applied_urls():
    """Return set of URLs already marked applied or skipped — skip these in results."""
    if not DB_PATH.exists():
        return set()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT url FROM jobs WHERE status IN ('applied', 'skipped')")
    urls = {row[0] for row in cur.fetchall()}
    conn.close()
    return urls


def save_jobs_to_db(jobs):
    """Insert newly found qualifying jobs (status=new). INSERT OR IGNORE preserves existing rows."""
    def _tier(score):
        if score >= 75: return "STRONG"
        if score >= 55: return "GOOD"
        if score >= 35: return "POSSIBLE"
        return "WEAK"
    conn = sqlite3.connect(DB_PATH)
    for j in jobs:
        conn.execute(
            """INSERT OR IGNORE INTO jobs (url, title, company, source, score, tier, status)
               VALUES (?, ?, ?, ?, ?, ?, 'new')""",
            (j.get("url", ""), j.get("title", ""), j.get("company", ""),
             j.get("source", ""), j.get("score", 0), _tier(j.get("score", 0)))
        )
    conn.commit()
    conn.close()


def polite_get(url, params=None, timeout=15, delay=1.5):
    """Fetch with a polite delay and error handling."""
    time.sleep(delay + random.uniform(0, 0.8))
    try:
        r = SESSION.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.exceptions.HTTPError as e:
        print(f"  ⚠ HTTP {e.response.status_code}: {url[:60]}", file=sys.stderr)
    except requests.exceptions.RequestException as e:
        print(f"  ⚠ Request error: {url[:60]} — {type(e).__name__}", file=sys.stderr)
    return None

# ─── BOARD FETCHERS ───────────────────────────────────────────────────────────

def fetch_weworkremotely():
    """We Work Remotely — largest dedicated remote job board, open RSS feed."""
    jobs = []
    feeds = [
        ("https://weworkremotely.com/categories/remote-programming-jobs.rss", "Programming"),
        ("https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss", "DevOps"),
    ]
    for feed_url, category in feeds:
        r = polite_get(feed_url)
        if not r:
            continue
        soup = BeautifulSoup(r.content, "lxml-xml")
        for item in soup.find_all("item"):
            title = item.find("title")
            link = item.find("link")
            pub = item.find("pubDate")
            desc = item.find("description")
            company_tag = item.find("company")

            title_text = title.get_text(strip=True) if title else ""
            # WWR titles often contain company: "Acme | Senior SDET"
            parts = title_text.split("|")
            company_name = parts[0].strip() if len(parts) > 1 else ""
            role_title = parts[-1].strip() if parts else title_text

            jobs.append({
                "title": role_title,
                "company": company_name or (company_tag.get_text(strip=True) if company_tag else ""),
                "location": "Remote",
                "url": link.get_text(strip=True) if link else "",
                "description": BeautifulSoup(desc.get_text(), "html.parser").get_text()[:2000] if desc else "",
                "salary": "",
                "posted": pub.get_text(strip=True) if pub else "",
                "source": "We Work Remotely",
            })
    print(f"    We Work Remotely: {len(jobs)} listings")
    return jobs


def fetch_jobicy():
    """Jobicy — remote-only board with open JSON API."""
    jobs = []
    r = polite_get("https://jobicy.com/api/v2/remote-jobs", params={
        "count": 50,
        "tag": "qa engineer",
    })
    if r:
        try:
            data = r.json()
            for j in data.get("jobs", []):
                jobs.append({
                    "title": j.get("jobTitle", ""),
                    "company": j.get("companyName", ""),
                    "location": j.get("jobGeo", "Remote"),
                    "url": j.get("url", ""),
                    "description": j.get("jobExcerpt", "") + " " + j.get("jobDescription", ""),
                    "salary": j.get("annualSalaryMin", "") or "",
                    "posted": j.get("pubDate", ""),
                    "source": "Jobicy",
                })
        except Exception as e:
            print(f"  ⚠ Jobicy parse error: {e}", file=sys.stderr)

    # Also search for SDET
    r2 = polite_get("https://jobicy.com/api/v2/remote-jobs", params={
        "count": 50,
        "tag": "sdet",
    })
    if r2:
        try:
            data2 = r2.json()
            existing_urls = {j["url"] for j in jobs}
            for j in data2.get("jobs", []):
                url = j.get("url", "")
                if url not in existing_urls:
                    jobs.append({
                        "title": j.get("jobTitle", ""),
                        "company": j.get("companyName", ""),
                        "location": j.get("jobGeo", "Remote"),
                        "url": url,
                        "description": j.get("jobExcerpt", "") + " " + j.get("jobDescription", ""),
                        "salary": j.get("annualSalaryMin", "") or "",
                        "posted": j.get("pubDate", ""),
                        "source": "Jobicy",
                    })
        except Exception:
            pass

    print(f"    Jobicy: {len(jobs)} listings")
    return jobs


def fetch_remoteok():
    """Remote OK — popular remote-only board with public JSON API."""
    jobs = []
    r = polite_get("https://remoteok.com/api", params={"tag": "quality-assurance"})
    if r:
        try:
            data = r.json()
            for j in data:
                if not isinstance(j, dict) or "position" not in j:
                    continue
                jobs.append({
                    "title": j.get("position", ""),
                    "company": j.get("company", ""),
                    "location": j.get("location", "Remote"),
                    "url": j.get("url", ""),
                    "description": j.get("description", ""),
                    "salary": f"${j['salary_min']}–${j['salary_max']}" if j.get("salary_min") else "",
                    "posted": datetime.utcfromtimestamp(j["epoch"]).strftime("%Y-%m-%dT%H:%M:%S") if j.get("epoch") else "",
                    "source": "Remote OK",
                })
        except Exception as e:
            print(f"  ⚠ RemoteOK parse error: {e}", file=sys.stderr)

    # Also fetch testing/QA
    r2 = polite_get("https://remoteok.com/api", params={"tag": "testing"})
    if r2:
        try:
            data2 = r2.json()
            existing = {j["url"] for j in jobs}
            for j in data2:
                if not isinstance(j, dict) or "position" not in j:
                    continue
                url = j.get("url", "")
                if url not in existing:
                    jobs.append({
                        "title": j.get("position", ""),
                        "company": j.get("company", ""),
                        "location": j.get("location", "Remote"),
                        "url": url,
                        "description": j.get("description", ""),
                        "salary": f"${j['salary_min']}–${j['salary_max']}" if j.get("salary_min") else "",
                        "posted": datetime.utcfromtimestamp(j["epoch"]).strftime("%Y-%m-%dT%H:%M:%S") if j.get("epoch") else "",
                        "source": "Remote OK",
                    })
        except Exception:
            pass

    print(f"    Remote OK: {len(jobs)} listings")
    return jobs


def fetch_linkedin_search(query, max_pages=2):
    """Scrape LinkedIn public job search (no login required for listings)."""
    jobs = []
    base_url = "https://www.linkedin.com/jobs/search/"
    for page in range(max_pages):
        params = {
            "keywords": query,
            "f_WT": "2",           # Remote filter
            "f_E": "4,5,6",        # Senior, Director, Executive experience levels
            "f_TPR": "r604800",    # Posted in last 7 days
            "geoId": "103644278",  # United States
            "start": page * 25,
            "position": 1,
            "pageNum": page,
        }
        r = polite_get(base_url, params=params, delay=2.5)
        if not r:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.find_all("div", class_=re.compile(r"job-search-card|base-card"))
        if not cards:
            # Try alternate selectors
            cards = soup.find_all("li", class_=re.compile(r"jobs-search"))
        for card in cards:
            title_el = card.find(["h3", "h4"], class_=re.compile(r"title|job-title"))
            company_el = card.find(["h4", "a"], class_=re.compile(r"company|subtitle"))
            location_el = card.find(["span", "div"], class_=re.compile(r"location|workplace"))
            link_el = card.find("a", href=re.compile(r"/jobs/view/"))
            time_el = card.find("time")

            title = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            location = location_el.get_text(strip=True) if location_el else "Remote"
            url = link_el["href"].split("?")[0] if link_el and link_el.get("href") else ""
            posted = time_el.get("datetime", "") if time_el else ""

            if title and url:
                jobs.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": url,
                    "description": f"{title} at {company}. Remote position.",
                    "salary": "",
                    "posted": posted,
                    "source": "LinkedIn",
                })
        time.sleep(random.uniform(2, 4))  # extra polite for LinkedIn
    return jobs


def fetch_linkedin_all():
    """Run multiple LinkedIn searches across all target role types."""
    all_jobs = []
    queries = [
        "senior software quality engineer",
        "SDET lead",
        "senior SDET",
        "software quality engineering manager",
        "lead software development engineer test",
        "software quality engineering lead",
        "senior test automation engineer",
        "QE lead software",
    ]
    seen = set()
    for q in queries:
        results = fetch_linkedin_search(q, max_pages=2)
        for j in results:
            if j["url"] not in seen:
                seen.add(j["url"])
                all_jobs.append(j)
        time.sleep(random.uniform(1, 2))
    print(f"    LinkedIn: {len(all_jobs)} listings")
    return all_jobs


def fetch_indeed_search(query):
    """Scrape Indeed public search results."""
    jobs = []
    url = "https://www.indeed.com/jobs"
    params = {
        "q": query,
        "l": "Remote",
        "sc": "0kf:attr(DSQF7)jt(fulltime);",  # remote filter
        "fromage": "7",  # last 7 days
        "sort": "date",
    }
    r = polite_get(url, params=params, delay=2.0)
    if not r:
        return jobs
    soup = BeautifulSoup(r.text, "html.parser")
    cards = soup.find_all("div", class_=re.compile(r"job_seen_beacon|resultContent|jobCard"))
    for card in cards:
        title_el = card.find(["h2", "a"], class_=re.compile(r"jobTitle|title"))
        company_el = card.find(["span", "div"], class_=re.compile(r"companyName|company"))
        location_el = card.find(["div", "span"], class_=re.compile(r"companyLocation|location"))
        salary_el = card.find(["div", "span"], class_=re.compile(r"salary|compensation"))
        link_el = card.find("a", href=re.compile(r"/rc/clk|/pagead"))
        date_el = card.find(["span"], class_=re.compile(r"date|posted"))

        title = title_el.get_text(strip=True) if title_el else ""
        company = company_el.get_text(strip=True) if company_el else ""
        location = location_el.get_text(strip=True) if location_el else "Remote"
        salary = salary_el.get_text(strip=True) if salary_el else ""
        posted_text = date_el.get_text(strip=True) if date_el else ""

        if link_el and link_el.get("href"):
            href = link_el["href"]
            job_url = f"https://www.indeed.com{href}" if href.startswith("/") else href
        else:
            job_url = ""

        # Convert "X days ago" to approximate date
        posted_date = ""
        if "today" in posted_text.lower() or "just" in posted_text.lower():
            posted_date = datetime.now().strftime("%Y-%m-%d")
        elif "day" in posted_text.lower():
            days_match = re.search(r"(\d+)", posted_text)
            if days_match:
                days = int(days_match.group(1))
                posted_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        if title and job_url:
            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "url": job_url,
                "description": f"{title} at {company}. {location}.",
                "salary": salary,
                "posted": posted_date,
                "source": "Indeed",
            })
    return jobs


def fetch_indeed_all():
    """Run multiple Indeed searches."""
    all_jobs = []
    queries = [
        "senior quality engineer",
        "SDET lead remote",
        "quality engineering manager remote",
        "quality automation lead",
        "lead software engineer in test",
    ]
    seen = set()
    for q in queries:
        results = fetch_indeed_search(q)
        for j in results:
            if j["url"] not in seen:
                seen.add(j["url"])
                all_jobs.append(j)
        time.sleep(random.uniform(1.5, 2.5))
    print(f"    Indeed: {len(all_jobs)} listings")
    return all_jobs


def fetch_greenhouse_boards():
    """
    Fetch from Greenhouse job boards of known Series C+ tech companies.
    Greenhouse exposes a public JSON API per company: https://boards-api.greenhouse.io/v1/boards/{company}/jobs
    Slugs last verified 2026-08-11; slugs that 404 are silently skipped.
    """
    companies = [
        # Already verified in earlier runs
        "figma", "lattice", "brex", "carta", "contentful",
        "postman", "launchdarkly", "pendo", "amplitude", "mixpanel",
        "datadog", "grafanalabs", "buildkite", "honeycomb", "saucelabs",
        # Additional verified 2026-08-11
        "databricks", "cloudflare", "fastly", "okta", "coinbase",
        "lyft", "airbnb", "stripe", "rubrik", "druva", "commvault",
        "gitlab", "jetbrains", "cockroachlabs", "yugabyte", "singlestore",
        "cybereason", "tanium", "zscaler", "netskope",
    ]
    jobs = []
    qe_keywords = ["quality", "sdet", "test", "qa", "automation"]
    for company in companies:
        url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
        r = polite_get(url, delay=0.5)
        if not r:
            continue
        try:
            data = r.json()
            for j in data.get("jobs", []):
                title = j.get("title", "").lower()
                if not any(k in title for k in qe_keywords):
                    continue
                location = j.get("location", {}).get("name", "") or ""
                loc_lower = location.lower()
                # Exclude explicitly non-US office locations
                non_us_offices = [
                    "london", "berlin", "amsterdam", "paris", "toronto",
                    "sydney", "melbourne", "bangalore", "hyderabad", "mumbai",
                    "singapore", "tokyo", "dublin", "warsaw",
                ]
                if any(c in loc_lower for c in non_us_offices):
                    continue
                jobs.append({
                    "title": j.get("title", ""),
                    "company": company.title(),
                    "location": location or "Remote",
                    "url": j.get("absolute_url", ""),
                    "description": j.get("title", ""),
                    "salary": "",
                    "posted": j.get("updated_at", "")[:10],
                    "source": "Greenhouse",
                })
        except Exception:
            pass
    print(f"    Greenhouse boards: {len(jobs)} listings")
    return jobs


def fetch_ashby_boards():
    """
    Fetch from Ashby job boards — the ATS most Series B/C startups migrated to.
    Public API: https://api.ashbyhq.com/posting-api/job-board/{slug}
    Slugs last verified 2026-08-07.
    """
    companies = [
        "notion", "linear", "temporal", "snyk", "confluent",
        "airtable", "clickup", "miro", "fullstory", "sentry",
        "loom", "ramp", "mercury", "vercel", "render",
        "neon", "supabase", "wiz", "launchdarkly", "bettercloud",
        "prefect", "airbyte", "hightouch", "amplitude", "qawolf",
    ]
    jobs = []
    qe_keywords = ["quality", "sdet", "test", "qa", "automation"]
    for company in companies:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
        r = polite_get(url, delay=0.4)
        if not r:
            continue
        try:
            data = r.json()
            for j in data.get("jobs", []):
                title = j.get("title", "").lower()
                if not any(k in title for k in qe_keywords):
                    continue
                workplace = j.get("workplaceType", "")
                is_fully_remote = workplace == "Remote" or (
                    j.get("isRemote", False) and workplace not in ("Hybrid", "OnSite", "On-Site")
                )
                if not is_fully_remote:
                    continue
                country = (j.get("address") or {}).get("postalAddress", {}).get("addressCountry", "")
                if country and country != "United States":
                    continue
                # Build a location string the scorer can use for US + remote signals
                if country == "United States":
                    location = "Remote, United States"
                else:
                    location = j.get("location", "Remote") or "Remote"
                desc_html = j.get("descriptionHtml", "") or ""
                desc_text = re.sub(r"<[^>]+>", " ", desc_html)[:2000]
                jobs.append({
                    "title": j.get("title", ""),
                    "company": company.title(),
                    "location": location,
                    "url": j.get("jobUrl", ""),
                    "description": desc_text,
                    "salary": "",
                    "posted": (j.get("publishedAt") or "")[:10],
                    "source": "Ashby",
                })
        except Exception:
            pass
    print(f"    Ashby boards: {len(jobs)} listings")
    return jobs


def fetch_lever_boards():
    """
    Fetch from Lever job boards — public JSON API per company slug.
    https://api.lever.co/v0/postings/{slug}?mode=json
    404s are silently skipped (many tech companies migrated to other ATS platforms).
    Slugs last verified 2026-08-11; add new slugs as you find them.
    """
    companies = [
        # Verified active on Lever as of 2026-08-11
        "ro", "secureframe", "plaid",
        # Likely on Lever — add more slugs here as you discover them
        "navan", "ironclad", "workos", "writer", "benchling", "gem",
        "vanta", "drata", "anecdotes", "abnormal-security", "huntress",
        "expel", "panther-labs", "cyera", "axonius",
    ]
    jobs = []
    qe_keywords = ["quality", "sdet", "test", "qa", "automation"]
    non_us_offices = [
        "london", "berlin", "amsterdam", "paris", "toronto", "vancouver",
        "sydney", "melbourne", "bangalore", "hyderabad", "mumbai", "delhi",
        "singapore", "tokyo", "dublin", "warsaw", "stockholm", "zurich", "lisbon",
    ]
    for company in companies:
        url = f"https://api.lever.co/v0/postings/{company}?mode=json"
        # Silence 404s — company not on Lever is expected, not an error
        time.sleep(0.4 + random.uniform(0, 0.3))
        try:
            r = SESSION.get(url, timeout=10)
            if r.status_code == 404:
                continue
            r.raise_for_status()
        except requests.exceptions.RequestException:
            continue
        if not r:
            continue
        try:
            data = r.json()
            if not isinstance(data, list):
                continue
            for j in data:
                title = j.get("text", "")
                if not any(k in title.lower() for k in qe_keywords):
                    continue
                categories = j.get("categories", {})
                location = categories.get("location", "") or ""
                loc_lower = location.lower()
                if any(c in loc_lower for c in non_us_offices):
                    continue
                # Parse createdAt (Unix ms)
                created_ms = j.get("createdAt", 0)
                posted = ""
                if created_ms:
                    try:
                        posted = datetime.utcfromtimestamp(created_ms / 1000).strftime("%Y-%m-%d")
                    except Exception:
                        pass
                desc_plain = (j.get("descriptionPlain") or "")[:2000]
                jobs.append({
                    "title": title,
                    "company": company.title(),
                    "location": location or "Remote",
                    "url": j.get("hostedUrl", ""),
                    "description": desc_plain,
                    "salary": "",
                    "posted": posted,
                    "source": "Lever",
                })
        except Exception:
            pass
    print(f"    Lever boards: {len(jobs)} listings")
    return jobs


# ─── SCORING ─────────────────────────────────────────────────────────────────
def parse_date(date_str):
    if not date_str:
        return None
    for fmt in [
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ",
        "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT",
    ]:
        try:
            dt = datetime.strptime(date_str[:25], fmt[:len(date_str[:25])])
            return dt.replace(tzinfo=None)
        except ValueError:
            continue
    return None


def score_job(job, since_days):
    score = 0
    reasons = []
    warnings = []
    title_lower = job["title"].lower()
    desc_lower = (job.get("description") or "").lower()
    loc_lower = (job.get("location") or "").lower()
    combined = f"{title_lower} {desc_lower} {loc_lower}"

    # ── Domain hard filter — exclude manufacturing / physical QE ──
    manufacturing_signals = [
        # Physical / industrial QE signals (appear in body text when description is available)
        "plant quality", "manufacturing quality", "assembly plant",
        "shop floor", "production quality", "supplier quality",
        "incoming inspection", "iso 9001", "iatf 16949", "as9100",
        "cmm", "metrology", "welding", "stamping", "machining",
        "manufacturing and quality", "quality and manufacturing",
        # Medical device / pharma regulated manufacturing
        "medical device", "iso 13485", "good manufacturing practice",
        " gmp ", "21 cfr", "fda regulated",
        # Title-level signals (caught even from sparse LinkedIn descriptions)
        "spring hill", "foundry", "castparts", "manufacturing recruiting",
    ]
    if any(s in combined for s in manufacturing_signals):
        return None, [], []
    # Aerospace — company name surfaces in LinkedIn description field
    if "aerospace" in combined and "quality" in title_lower:
        return None, [], []

    # ── Hard filter: hybrid / on-site work arrangements ──
    # "hybrid" in location or description means not fully remote — hard stop.
    if "hybrid" in loc_lower:
        return None, [], []
    hybrid_desc_signals = [
        "hybrid work", "hybrid position", "hybrid role", "hybrid model",
        "hybrid schedule", "hybrid arrangement", "hybrid work arrangement",
        "days per week in office", "days in the office", "days in office",
        "in-office requirement", "days on-site", "days onsite",
        "days per week onsite", "required to be in office",
    ]
    if any(s in desc_lower for s in hybrid_desc_signals):
        return None, [], []

    # ── Title relevance (0–30) ──
    exact_hits = [t for t in PROFILE["target_titles"] if t.lower() in title_lower]
    qe_partial = ["quality", "sdet", "test engineer", "qa engineer",
                  "automation engineer", "test automation"]
    if exact_hits:
        score += 30
        reasons.append(f"Title: {exact_hits[0]}")
    elif any(k in title_lower for k in qe_partial):
        score += 15
        reasons.append("Partial title match")
    else:
        return None, [], []  # Irrelevant — skip entirely

    # ── Seniority (0–20) ──
    senior_hits = [s for s in PROFILE["seniority_keywords"] if s in combined[:600]]
    if senior_hits:
        score += 20
        reasons.append(f"Seniority: {senior_hits[0]}")
    else:
        warnings.append("Seniority unclear")
        score += 3

    # ── Remote status (0–20) ──
    remote_positive = ["remote", "worldwide", "anywhere", "distributed",
                       "work from home", "wfh", "fully remote", "100% remote"]
    avoid = PROFILE["avoid_keywords"]
    if any(s in combined for s in remote_positive):
        score += 20
        reasons.append("Remote confirmed")
    elif any(s in combined for s in avoid):
        warnings.append("⚠ Non-remote or junior signals")
        score -= 20
    else:
        warnings.append("Remote unconfirmed — verify")
        score += 5

    # ── US eligibility — HARD FILTER ──
    # These checks are unconditional: a non-US location wins even if the
    # description mentions "United States" somewhere in boilerplate.
    non_us = PROFILE["non_us_signals"]
    us_pos  = PROFILE["us_positive_signals"]

    # 1. Explicit non-US phrases anywhere in the listing
    if any(s in combined for s in non_us):
        return None, [], []

    # 2. Location field targets a non-US geographic region — hard stop
    non_us_loc_regions = [
        "latam", "emea", "apac", "latin america", "south america",
        "central america", "asia pacific",
    ]
    if any(r in loc_lower for r in non_us_loc_regions):
        return None, [], []

    # 3. Location field names a specific non-US country — hard stop
    non_us_countries = [
        "united kingdom", "germany", "france", "netherlands", "spain",
        "italy", "poland", "portugal", "sweden", "norway", "denmark",
        "finland", "austria", "belgium", "switzerland", "ireland",
        "australia", "new zealand", "india", "singapore", "japan",
        "brazil", "mexico", "colombia", "argentina", "nigeria",
        "south africa", "kenya", "pakistan", "bangladesh",
        "costa rica", "guatemala", "panama", "honduras", "el salvador",
        "nicaragua", "chile", "peru", "ecuador", "bolivia", "uruguay",
        "paraguay", "venezuela", "ghana", "egypt", "turkey",
        "ukraine", "china", "taiwan", "south korea", "thailand",
        "vietnam", "philippines", "indonesia", "malaysia",
    ]
    if any(c in loc_lower for c in non_us_countries):
        return None, [], []

    # 4. US-positive signals → bonus; silence → warn
    if any(s in combined for s in us_pos):
        score += 10
        reasons.append("US-based role confirmed")
    else:
        warnings.append("US eligibility unconfirmed — verify before applying")

    # ── Skills match (0–20) ──
    hits = [s for s in PROFILE["top_skills"] if s.lower() in combined]
    if len(hits) >= 4:
        score += 20
        reasons.append(f"Skills: {', '.join(hits[:4])}")
    elif len(hits) >= 2:
        score += 12
        reasons.append(f"Skills: {', '.join(hits[:3])}")
    elif hits:
        score += 5
        reasons.append(f"Skill: {hits[0]}")
    else:
        warnings.append("No specific skills mentioned in listing")

    # ── Salary (0–10) ──
    salary = str(job.get("salary", "") or "")
    if salary.strip():
        score += 10
        reasons.append(f"Salary listed: {salary[:50]}")
        nums = re.findall(r"\d[\d,]+", salary)
        if nums:
            val = int(nums[0].replace(",", ""))
            if val < 80_000:
                warnings.append(f"Salary may be low: {salary}")
                score -= 5
    else:
        warnings.append("Salary not listed")

    # ── Recency (0–10 bonus) ──
    dt = parse_date(job.get("posted", ""))
    if dt:
        days_old = (datetime.now() - dt).days
        if days_old <= since_days:
            score += 10
            reasons.append(f"Posted {days_old}d ago ✓")
        elif days_old <= 7:
            score += 5
            reasons.append(f"Posted {days_old}d ago")
        elif days_old <= 14:
            reasons.append(f"Posted {days_old}d ago")
        else:
            warnings.append(f"Older listing: {days_old}d ago")
            score -= 5
    else:
        warnings.append("Post date unknown")

    # ── Preferred company signals (bonus 5) ──
    if any(s in combined for s in PROFILE["preferred_company_signals"]):
        score += 5
        reasons.append("Growth-stage company signals")

    return max(0, min(100, score)), reasons, warnings


# ─── OUTPUT ──────────────────────────────────────────────────────────────────
def tier(score):
    if score >= 75: return "🟢 STRONG FIT"
    if score >= 55: return "🟡 GOOD FIT"
    if score >= 35: return "🟠 POSSIBLE"
    return "🔴 WEAK"


def format_markdown(jobs, since_days, run_time, board_counts):
    lines = [
        "# QE Job Search Results — Arielle Israel",
        f"**Run:** {run_time}  |  **Roles found:** {len(jobs)}  |  **Filter:** Last {since_days} days, remote only",
        "",
        "### Boards searched",
        *[f"- {b}: {c} listings" for b, c in board_counts.items()],
        "", "---", "",
    ]
    for i, j in enumerate(jobs, 1):
        lines += [
            f"## {i}. {j['title']} — {j['company']}",
            f"**Score:** {j['score']}/100 · {tier(j['score'])}  |  **Source:** {j['source']}",
            f"**Location:** {j['location']}  |  **Salary:** {j['salary'] or 'Not listed'}",
            f"**Posted:** {j.get('posted', 'Unknown')[:10]}",
            f"**Apply:** {j['url']}",
            "",
            f"**Why it fits:** {' · '.join(j['reasons']) or 'Partial match'}",
        ]
        if j["warnings"]:
            lines.append(f"**Watch:** {' · '.join(j['warnings'])}")
        lines += ["", "---", ""]
    return "\n".join(lines)


# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="QE Job Search Agent v2")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--since", type=int, default=3)
    parser.add_argument("--min-score", type=int, default=35)
    parser.add_argument("--skip-linkedin", action="store_true", help="Skip LinkedIn scraping")
    parser.add_argument("--skip-indeed", action="store_true", help="Skip Indeed scraping")
    parser.add_argument("--ignore-db", action="store_true", help="Skip applied-jobs DB filter")
    args = parser.parse_args()

    if not args.ignore_db:
        init_db()

    run_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n🔍 QE Job Search Agent v2 — {run_time}")
    print(f"   Profile: {PROFILE['name']} | Remote only | ${PROFILE['salary_min']:,}–${PROFILE['salary_max']:,}")
    print(f"   Filtering: posted within {args.since} days | min score {args.min_score}\n")

    all_jobs = []
    board_counts = {}

    boards = [
        ("We Work Remotely", fetch_weworkremotely),
        ("Jobicy",           fetch_jobicy),
        ("Remote OK",        fetch_remoteok),
        ("Greenhouse",       fetch_greenhouse_boards),
        ("Ashby",            fetch_ashby_boards),
        ("Lever",            fetch_lever_boards),
    ]
    if not args.skip_linkedin:
        boards.append(("LinkedIn", fetch_linkedin_all))
    if not args.skip_indeed:
        boards.append(("Indeed", fetch_indeed_all))

    for board_name, fetcher in boards:
        print(f"  → {board_name}...")
        try:
            results = fetcher()
            board_counts[board_name] = len(results)
            all_jobs.extend(results)
        except Exception as e:
            print(f"  ⚠ {board_name} failed: {e}", file=sys.stderr)
            board_counts[board_name] = 0

    print(f"\n  Raw total: {len(all_jobs)} listings across {len(boards)} boards")

    # Deduplicate by URL
    seen, unique = set(), []
    for j in all_jobs:
        url = j.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(j)
    print(f"  After dedup: {len(unique)} unique listings")

    # Filter out jobs already applied to or explicitly skipped
    if not args.ignore_db:
        applied_urls = load_applied_urls()
        before = len(unique)
        unique = [j for j in unique if j.get("url", "") not in applied_urls]
        filtered = before - len(unique)
        if filtered:
            print(f"  After DB filter: {len(unique)} (skipped {filtered} already applied/skipped)")

    print(f"  Scoring...\n")

    # Score
    scored = []
    for j in unique:
        score, reasons, warnings = score_job(j, args.since)
        if score is not None and score >= args.min_score:
            scored.append({**j, "score": score, "reasons": reasons, "warnings": warnings})

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Persist new qualifying jobs so the autofiller can mark them applied/skipped
    if not args.ignore_db and scored:
        save_jobs_to_db(scored)
        print(f"  💾 {len(scored)} jobs saved to {DB_PATH.name}")

    strong = [j for j in scored if j["score"] >= 75]
    good   = [j for j in scored if 55 <= j["score"] < 75]
    maybe  = [j for j in scored if j["score"] < 55]

    print(f"{'='*62}")
    print(f"  RESULTS: {len(scored)} qualifying roles")
    print(f"  🟢 Strong fit: {len(strong)}  🟡 Good: {len(good)}  🟠 Possible: {len(maybe)}")
    print(f"{'='*62}\n")

    for j in scored[:25]:
        print(f"{tier(j['score'])} [{j['score']:3}/100]  {j['title']}")
        print(f"   {j['company']}  |  {j['source']}  |  {j['location']}")
        if j["salary"]:
            print(f"   💰 {j['salary']}")
        print(f"   🔗 {j['url']}")
        if j["reasons"]:
            print(f"   ✓ {' · '.join(j['reasons'][:3])}")
        if j["warnings"]:
            print(f"   ! {' · '.join(j['warnings'][:2])}")
        print()

    if args.save and scored:
        out = Path("results")
        out.mkdir(exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")

        csv_path = out / f"jobs_{date_str}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "score","tier","title","company","location","salary",
                "posted","source","url","reasons","warnings"
            ])
            writer.writeheader()
            for j in scored:
                writer.writerow({
                    "score": j["score"],
                    "tier": tier(j["score"]),
                    "title": j["title"],
                    "company": j["company"],
                    "location": j["location"],
                    "salary": j["salary"],
                    "posted": j.get("posted", "")[:10],
                    "source": j["source"],
                    "url": j["url"],
                    "reasons": " | ".join(j["reasons"]),
                    "warnings": " | ".join(j["warnings"]),
                })
        print(f"💾 CSV saved: {csv_path}  ({len(scored)} roles)")

        md_path = out / f"jobs_{date_str}.md"
        md_path.write_text(format_markdown(scored, args.since, run_time, board_counts), encoding="utf-8")
        print(f"💾 Markdown: {md_path}")

    print(f"\n✅ Done. Review your 🟢 Strong Fit roles first.")
    return scored


if __name__ == "__main__":
    main()
