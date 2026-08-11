# Job Application Auto-Filler — Arielle Israel

Playwright-based tool that pre-fills job application forms with your info,
attaches your resume, and pauses for YOU to review and click submit.

---

## One-Time Setup (5 minutes)

### 1. Install dependencies
```bash
pip install playwright
playwright install chromium
```

### 2. Add your resume PDF
Copy your resume PDF to your job-search folder:
```
~/Documents/job-search/resume.pdf
```
Or update the path in the script at:
```python
"resume_path": str(Path.home() / "Documents" / "job-search" / "resume.pdf"),
```

### 3. Fill in your details (one time)
Open `autofiller.py` and update the PROFILE section at the top:
- Phone number
- LinkedIn URL
- Zip code

Everything else is already populated from your info.

---

## Daily Usage

### Run on today's job results (Strong fits only — recommended first)
```bash
python3 autofiller.py --jobs results/jobs_2026-08-06.csv --tier STRONG
```

### Run on all qualifying roles, cap at 50
```bash
python3 autofiller.py --jobs results/jobs_2026-08-06.csv --limit 50
```

### Run on a single URL
```bash
python3 autofiller.py --url "https://boards.greenhouse.io/company/jobs/123"
```

### Skip LinkedIn/Indeed (use for Greenhouse + Lever roles only)
```bash
python3 autofiller.py --jobs results/jobs_today.csv --tier GOOD --limit 30
```

---

## How Each Application Works

1. Browser opens the job URL automatically
2. Script detects the platform (LinkedIn, Greenhouse, Lever, Indeed, or generic)
3. Clicks Apply / Easy Apply if needed
4. Pre-fills all form fields it can find:
   - Name, email, phone, location
   - LinkedIn URL, years of experience
   - Work authorization (Yes/No radios)
   - Cover note in any text fields
5. Attaches your resume PDF
6. **Pauses and shows you the form**
7. You review, make any adjustments, and click Submit
8. Press ENTER in the terminal to move to the next application
   - Type `s` + ENTER to skip a role
   - Type `q` + ENTER to end the session

---

## Platform Support

| Platform | What it automates |
|---|---|
| LinkedIn Easy Apply | Clicks Easy Apply, fills modal form, attaches resume |
| Greenhouse | Fills full application form, attaches resume |
| Lever | Fills full application form, attaches resume |
| Indeed | Clicks Apply, fills form, attaches resume |
| Generic | Finds any Apply button, fills all visible fields |

---

## Tips for Speed

- Run `--tier STRONG` first each morning — these get your full attention
- Run `--tier GOOD --limit 30` after for volume
- The browser stays open between fields so you can spot-check
- If a field doesn't fill correctly, just type over it — takes 2 seconds
- LinkedIn Easy Apply often has multi-step modals — click Next between steps,
  the script will have filled what it can on each page

---

## Recommended Daily Flow

| Time | Action |
|---|---|
| 8:00am | Agent runs, saves results/jobs_today.csv |
| 8:05am | `python3 autofiller.py --jobs results/jobs_today.csv --tier STRONG` |
| 9:00am | `python3 autofiller.py --jobs results/jobs_today.csv --tier GOOD --limit 40` |
| 10:00am | Use Playbook Prompt 2 for recruiter outreach |
| EOD | Log numbers in dashboard |
