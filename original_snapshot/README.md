# MEDD Maharashtra — Static Decision Support Dashboard

A single self-contained `index.html`. Every KPI, chart, table, and the division
heat-map are computed from the master Excel and embedded directly in the file —
there is no backend and no build step.

## What's inside
- Executive KPIs (Required, Available, Functional, Non-Functional, Procurement,
  Gap %, Budget, AMC, Condemnation) — all from the master Excel.
- Image-based division heat map (your official 6-division map) with colour-tinted
  regions and gap markers; click a division to filter the whole dashboard.
- Procurement, budget, equipment-status and cost-category charts (Chart.js via CDN).
- Top institutes by gap and top equipment by procurement need.
- Data-quality notes.

All headline figures match the official KPI Output workbook
(Budget ₹6,139,631,348 · Gap 126.16% · 35 institutes · 6 divisions).

## Deploy to Netlify

Option A — drag & drop (fastest):
1. Go to https://app.netlify.com/drop
2. Drag this entire folder onto the page. Done.

Option B — Git / CLI:
1. Push this folder to a Git repo and "Add new site" in Netlify, OR
2. Install the CLI and run:  `netlify deploy --prod --dir .`

No build command and no environment variables are needed. `netlify.toml` sets
the publish directory to the folder root; `_redirects` is a backup for the same.

## Updating the data
Re-run the data-extraction step against a new master Excel to regenerate the
embedded payload, then replace `index.html`. The numbers are a snapshot — they do
not change live, because there is no server.

## Note
This static build is separate from the full React + FastAPI application. Use this
when you need a zero-infrastructure, shareable snapshot. Use the full app when you
need live filtering against the database and the complete set of dashboards.
