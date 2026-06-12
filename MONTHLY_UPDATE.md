# 🔄 Monthly update — 4 steps, ~5 minutes

Your monthly file set (download from nseindia.com → Invest → Grievance
Redressal Reports):
  1. isc_report1C_*.xls   ← REQUIRED (core dashboard)
  2. isc_report1A_*.xls   ← complaint-level detail
  3. isc_report3B_*.xls   ← arbitration
  4. isc_report4B_*.xls   ← penal actions

Any filename works — report types are detected from the file CONTENT,
not the name. Suffixes like "__1_" are fine.

## If your GitHub Pages source = "GitHub Actions" (recommended)
  1. Delete last month's files from data/reports/ in the repo
  2. Upload the 4 new files there
  3. Commit → push
  4. Done — the site regenerates and republishes itself (~2 min)

## If your GitHub Pages source = "Deploy from a branch"
  1. Put the 4 new files in data/reports/ locally
  2. Run:  python generate_dashboard.py
  3. Commit the updated index.html → push
  4. Live in ~1 min

## Netlify Drop
  Regenerate locally (step 2 above), then drag index.html to
  app.netlify.com/drop → same URL updates instantly.
