# AquaPrior – Where Should We Recharge?  (AWS Environmental Hackathon)
Explainable groundwater-recharge priority map + budget optimizer + what-if + AI agent, for Pune region, Maharashtra (stable grid zone IDs; offline demo ready).

```
frontend/   React + Leaflet dashboard (6 screens)           backend/   Lambda API + Strands agent + SAM template
analysis/   data pipeline (wells -> scores)                 data/      generated JSON/CSV (zones, wells, meta)
docs/       FEATURES (start here), ARCHITECTURE, ASSUMPTIONS, DEMO_SCRIPT, CHECKLIST      demo/   screenshots + video go here
```

## Fastest path (5 minutes, no AWS needed)
```powershell
cd frontend
npm install
npm run dev        # open the printed http://localhost:5173 link (internet needed for map tiles)
```
The app runs in **offline demo mode** with the full engine in the browser. Everything below is optional upgrades.

**Read `docs/FEATURES.md` next: every feature, one by one, with what it does, where the code is, and how to switch it on.**
