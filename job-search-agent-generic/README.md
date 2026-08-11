# Job Search Agent

A daily job search agent that scans multiple remote job boards, scores each role
against your profile, and delivers a ranked list ready to review and apply to.

---

## Quick Start (10 minutes)

### 1. Install Claude Code
Download from claude.ai/code — installs in ~2 minutes.

### 2. Copy this folder
Put the entire `job-search-agent` folder anywhere on your computer, e.g.:
```
~/Documents/job-search-agent/
```

### 3. Set up your profile
```bash
cd ~/Documents/job-search-agent
cp profile_template.json profile.json
```
Open `profile.json` in any text editor and fill in your details:
- **name** — your name (used in output headers)
- **target_titles** — exact job titles you're targeting
- **search_queries** — search terms to use on LinkedIn/Indeed (add "remote" to each)
- **job_keywords** — short keywords that appear in relevant job titles (e.g. "engineer", "developer")
- **salary_min / salary_max** — your target range
- **top_skills** — your key technical skills to match against listings
- **avoid_keywords** — words that disqualify a listing (e.g. "on-site only", "junior")
- **domain_avoid_keywords** — industry-specific terms that mean the wrong type of role (leave empty `[]` if not needed)
- **greenhouse_companies / ashby_companies** — companies whose job boards to check directly

### 4. Run your first search
```bash
python3 job_search_agent.py --since 3
```
This searches for jobs posted in the last 3 days and prints ranked results.

### 5. Save results to files
```bash
python3 job_search_agent.py --since 3 --save
```
Creates `results/jobs_YYYY-MM-DD.csv` and `results/jobs_YYYY-MM-DD.md`

---

## Schedule It (runs automatically every morning)

### macOS — cron
```bash
crontab -e
```
Add this line (runs at 8am every weekday):
```
0 8 * * 1-5 cd ~/Documents/job-search-agent && python3 job_search_agent.py --since 1 --save >> logs/search.log 2>&1
```

### Windows — Task Scheduler
1. Open Task Scheduler → Create Basic Task
2. Trigger: Daily, 8:00 AM
3. Action: Start a program
4. Program: `python`
5. Arguments: `C:\path\to\job_search_agent.py --since 1 --save`

---

## Options

| Flag | Default | Description |
|---|---|---|
| `--since N` | 3 | Only show jobs posted in last N days |
| `--save` | off | Save results to CSV + Markdown in results/ |
| `--min-score N` | 35 | Minimum fit score (0–100) to include |
| `--skip-linkedin` | off | Skip LinkedIn scraping (faster runs) |
| `--skip-indeed` | off | Skip Indeed scraping (faster runs) |

---

## Fit Score Breakdown

| Score | Label | Meaning |
|---|---|---|
| 75–100 | 🟢 STRONG FIT | Apply first, fully tailor resume |
| 55–74 | 🟡 GOOD FIT | Apply with quick tailoring |
| 35–54 | 🟠 POSSIBLE | Review manually — may be worth it |
| <35 | 🔴 WEAK | Skip |

---

## Job Boards Searched

| Board | What it covers |
|---|---|
| We Work Remotely | Remote-only tech roles worldwide |
| Jobicy | Remote-only board with open API |
| Remote OK | Popular remote-only board with public API |
| Greenhouse | Direct company job boards (configurable list) |
| Ashby | Direct company job boards (configurable list) |
| LinkedIn | Public job search (no login required) |
| Indeed | Public job search |

### Tip: Targeting Specific Companies
Edit `greenhouse_companies` and `ashby_companies` in your `profile.json` to add or remove companies whose boards you want to check directly. Many Series B–D startups use one of these two ATS platforms.

---

## Customizing Your Profile

All behavior is controlled by `profile.json`. Key fields to tune after your first run:

- **job_keywords** — if you're getting unrelated results, tighten these to more specific terms
- **domain_avoid_keywords** — if your field name overlaps with an unrelated industry (e.g. "quality engineer" appears in manufacturing), add phrases like `"manufacturing quality"`, `"iso 9001"` here
- **avoid_keywords** — add any patterns from results you don't want to see
- **seniority_keywords** — if you're targeting a specific level, adjust (e.g. remove "manager" if you don't want people-management roles)
