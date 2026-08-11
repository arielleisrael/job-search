# QE Job Search Agent — Arielle Israel

A daily job search agent that scans multiple remote job boards, scores each role
against your profile, and delivers a ranked list ready to review and apply to.

---

## Quick Start (5 minutes)

### 1. Install Claude Code
Download from claude.ai/code — installs in ~2 minutes.

### 2. Copy this folder
Put `job_search_agent.py` anywhere on your computer, e.g.:
```
~/Documents/job-search/job_search_agent.py
```

### 3. Run your first search
Open Terminal and run:
```bash
cd ~/Documents/job-search
python3 job_search_agent.py --since 3
```
This searches for jobs posted in the last 3 days and prints ranked results.

### 4. Save results to files
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
0 8 * * 1-5 cd ~/Documents/job-search && python3 job_search_agent.py --since 1 --save >> logs/search.log 2>&1
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
| Remotive | Remote-only QA / software roles worldwide |
| The Muse | Senior-level remote roles at growth companies |
| Arbeitnow | Remote-verified tech roles, Europe + global |

### Adding More Boards
To add LinkedIn, Indeed, or Greenhouse roles, paste job descriptions
directly into Claude with your Prompt 1 (Resume Tailoring) or Prompt 4 (Job Ranking)
from your Playbook. The agent covers boards with open APIs — LinkedIn/Indeed
require paid API access or manual search.

---

## Recommended Daily Workflow

1. **8am** — Agent runs automatically, saves results/jobs_TODAY.csv
2. **Morning** — Open the CSV, review 🟢 Strong Fit roles first
3. **Tailor** — Use Playbook Prompt 1 for each 🟢 role
4. **Apply** — Hit 100 applications across agent results + LinkedIn Easy Apply + Indeed
5. **Outreach** — Use Playbook Prompt 2 for recruiter DMs
6. **Log** — Update your dashboard at end of day

---

## Updating Your Profile
Edit the `PROFILE` dict at the top of `job_search_agent.py` to adjust:
- Target titles
- Skills keywords
- Salary range
- Avoid keywords
