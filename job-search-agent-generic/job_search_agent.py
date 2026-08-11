#!/usr/bin/env python3
"""
Generic Job Search Agent
Searches remote job boards, scores each role against your profile,
and delivers a ranked list ready to review and apply to.

Setup:
  1. Copy profile_template.json → profile.json
  2. Fill in profile.json with your details
  3. Run: python3 job_search_agent.py

Usage:
  python3 job_search_agent.py              # run search, print results
  python3 job_search_agent.py --save       # save to CSV + markdown
  python3 job_search_agent.py --since 7    # jobs posted in last N days (default: 3)
  python3 job_search_agent.py --min-score 40  # raise fit threshold

Dependencies (auto-installed on first run):
  pip install requests beautifulsoup4 lxml
"""

import sys
import subprocess

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

# ─── PROFILE LOADING ──────────────────────────────────────────────────────────

PROFILE_PATH = Path(__file__).parent / "profile.json"

def load_profile():
    if not PROFILE_PATH.exists():
        print("❌  profile.json not found.")
        print("    Copy profile_template.json → profile.json and fill in your details.")
        print(f"    Expected location: {PROFILE_PATH}")
        sys.exit(1)
    with open(PROFILE_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    if "_instructions" in raw:
        del raw["_instructions"]
    required = ["name", "target_titles", "search_queries", "job_keywords", "top_skills"]
    missing = [k for k in required if not raw.get(k)]
    if missing:
        print(f"❌  profile.json is missing required fields: {', '.join(missing)}")
        print("    Check profile_template.json for the expected format.")
        sys.exit(1)
    return raw

PROFILE = load_profile()

# ─── HTTP ─────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

def polite_get(url, params=None, timeout=15, delay=1.5):
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
    jobs = []
    job_keywords = PROFILE.get("job_keywords", [])
    seen_urls = set()

    for keyword in job_keywords[:3]:  # limit to first 3 to avoid too many requests
        r = polite_get("https://jobicy.com/api/v2/remote-jobs", params={
            "count": 50,
            "tag": keyword,
        })
        if not r:
            continue
        try:
            data = r.json()
            for j in data.get("jobs", []):
                url = j.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
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
        except Exception as e:
            print(f"  ⚠ Jobicy parse error: {e}", file=sys.stderr)

    print(f"    Jobicy: {len(jobs)} listings")
    return jobs


def fetch_remoteok():
    jobs = []
    job_keywords = PROFILE.get("job_keywords", [])
    seen_urls = set()

    tags_to_search = []
    for kw in job_keywords[:2]:
        tags_to_search.append(kw.lower().replace(" ", "-"))

    for tag in tags_to_search:
        r = polite_get("https://remoteok.com/api", params={"tag": tag})
        if not r:
            continue
        try:
            data = r.json()
            for j in data:
                if not isinstance(j, dict) or "position" not in j:
                    continue
                url = j.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
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
        except Exception as e:
            print(f"  ⚠ RemoteOK parse error: {e}", file=sys.stderr)

    print(f"    Remote OK: {len(jobs)} listings")
    return jobs


def fetch_linkedin_search(query, max_pages=2):
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
        time.sleep(random.uniform(2, 4))
    return jobs


def fetch_linkedin_all():
    all_jobs = []
    queries = PROFILE.get("search_queries", [])
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
    jobs = []
    url = "https://www.indeed.com/jobs"
    params = {
        "q": query,
        "l": "Remote",
        "sc": "0kf:attr(DSQF7)jt(fulltime);",
        "fromage": "7",
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
    all_jobs = []
    queries = PROFILE.get("search_queries", [])
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
    companies = PROFILE.get("greenhouse_companies", [
        "figma", "lattice", "brex", "carta", "contentful",
        "postman", "launchdarkly", "pendo", "amplitude", "mixpanel",
        "datadog", "grafanalabs", "buildkite", "honeycomb", "saucelabs",
    ])
    job_keywords = [k.lower() for k in PROFILE.get("job_keywords", [])]
    jobs = []
    for company in companies:
        url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
        r = polite_get(url, delay=0.5)
        if not r:
            continue
        try:
            data = r.json()
            for j in data.get("jobs", []):
                title_lower = j.get("title", "").lower()
                if not any(k in title_lower for k in job_keywords):
                    continue
                location = j.get("location", {}).get("name", "") or ""
                loc_lower = location.lower()
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
    companies = PROFILE.get("ashby_companies", [
        "notion", "linear", "temporal", "snyk", "confluent",
        "airtable", "clickup", "miro", "fullstory", "sentry",
        "loom", "ramp", "mercury", "vercel", "render",
    ])
    job_keywords = [k.lower() for k in PROFILE.get("job_keywords", [])]
    jobs = []
    for company in companies:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
        r = polite_get(url, delay=0.4)
        if not r:
            continue
        try:
            data = r.json()
            for j in data.get("jobs", []):
                title_lower = j.get("title", "").lower()
                if not any(k in title_lower for k in job_keywords):
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
                location = "Remote, United States" if country == "United States" else (j.get("location", "Remote") or "Remote")
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

    # ── Domain hard filter (configurable via domain_avoid_keywords in profile) ──
    domain_avoid = [k.lower() for k in PROFILE.get("domain_avoid_keywords", [])]
    if domain_avoid and any(s in combined for s in domain_avoid):
        return None, [], []

    # ── Title relevance (0–30) ──
    target_titles = [t.lower() for t in PROFILE.get("target_titles", [])]
    job_keywords = [k.lower() for k in PROFILE.get("job_keywords", [])]

    exact_hits = [t for t in target_titles if t in title_lower]
    if exact_hits:
        score += 30
        reasons.append(f"Title: {exact_hits[0]}")
    elif any(k in title_lower for k in job_keywords):
        score += 15
        reasons.append("Partial title match")
    else:
        return None, [], []  # Irrelevant — skip entirely

    # ── Seniority (0–20) ──
    senior_hits = [s for s in PROFILE.get("seniority_keywords", []) if s in combined[:600]]
    if senior_hits:
        score += 20
        reasons.append(f"Seniority: {senior_hits[0]}")
    else:
        warnings.append("Seniority unclear")
        score += 3

    # ── Remote status (0–20) ──
    remote_positive = ["remote", "worldwide", "anywhere", "distributed",
                       "work from home", "wfh", "fully remote", "100% remote"]
    avoid = [k.lower() for k in PROFILE.get("avoid_keywords", [])]
    if any(s in combined for s in remote_positive):
        score += 20
        reasons.append("Remote confirmed")
    elif any(s in combined for s in avoid):
        warnings.append("⚠ Non-remote or undesired role signals")
        score -= 20
    else:
        warnings.append("Remote unconfirmed — verify")
        score += 5

    # ── US eligibility hard filters ──
    non_us = PROFILE.get("non_us_signals", [])
    us_pos = PROFILE.get("us_positive_signals", [])

    if any(s in combined for s in non_us):
        return None, [], []

    non_us_loc_regions = [
        "latam", "emea", "apac", "latin america", "south america",
        "central america", "asia pacific",
    ]
    if any(r in loc_lower for r in non_us_loc_regions):
        return None, [], []

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

    if any(s in combined for s in us_pos):
        score += 10
        reasons.append("US-based role confirmed")
    else:
        warnings.append("US eligibility unconfirmed — verify before applying")

    # ── Skills match (0–20) ──
    top_skills = [s.lower() for s in PROFILE.get("top_skills", [])]
    hits = [s for s in top_skills if s in combined]
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
    salary_min = PROFILE.get("salary_min", 0)
    if salary.strip():
        score += 10
        reasons.append(f"Salary listed: {salary[:50]}")
        nums = re.findall(r"\d[\d,]+", salary)
        if nums:
            val = int(nums[0].replace(",", ""))
            if salary_min and val < salary_min * 0.8:
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
    if any(s in combined for s in PROFILE.get("preferred_company_signals", [])):
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
    name = PROFILE.get("name", "Job Seeker")
    lines = [
        f"# Job Search Results — {name}",
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
    parser = argparse.ArgumentParser(description="Generic Job Search Agent")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--since", type=int, default=3)
    parser.add_argument("--min-score", type=int, default=35)
    parser.add_argument("--skip-linkedin", action="store_true", help="Skip LinkedIn scraping")
    parser.add_argument("--skip-indeed", action="store_true", help="Skip Indeed scraping")
    args = parser.parse_args()

    name = PROFILE.get("name", "Job Seeker")
    salary_min = PROFILE.get("salary_min", 0)
    salary_max = PROFILE.get("salary_max", 0)
    run_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    salary_str = f"${salary_min:,}–${salary_max:,}" if salary_min and salary_max else "not specified"
    print(f"\n🔍 Job Search Agent — {run_time}")
    print(f"   Profile: {name} | Remote only | {salary_str}")
    print(f"   Filtering: posted within {args.since} days | min score {args.min_score}\n")

    all_jobs = []
    board_counts = {}

    boards = [
        ("We Work Remotely", fetch_weworkremotely),
        ("Jobicy",           fetch_jobicy),
        ("Remote OK",        fetch_remoteok),
        ("Greenhouse",       fetch_greenhouse_boards),
        ("Ashby",            fetch_ashby_boards),
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

    seen, unique = set(), []
    for j in all_jobs:
        url = j.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(j)
    print(f"  After dedup: {len(unique)} unique listings")
    print(f"  Scoring...\n")

    scored = []
    for j in unique:
        score, reasons, warnings = score_job(j, args.since)
        if score is not None and score >= args.min_score:
            scored.append({**j, "score": score, "reasons": reasons, "warnings": warnings})

    scored.sort(key=lambda x: x["score"], reverse=True)

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
        out = Path(__file__).parent / "results"
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
