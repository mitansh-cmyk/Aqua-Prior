# Features, one by one
Status: ✅ working now · 🔧 needs one step from you (listed) · ⚠️ limitation to state honestly.

## 1. Data pipeline (analysis/)  ✅
Real India-WRIS wells -> 145 usable Pune wells (>=6 pre-monsoon years, 2009-2023) -> per-well depth, decline (m/yr), post-monsoon recovery.
Re-run (optional, outputs are already in `data/`):
```powershell
pip install pandas numpy scipy scikit-learn xgboost
cd analysis
python score_pune.py --src "C:\path\to\groundwater-level-collected-manually.csv"
copy ..\data\zones.json ..\frontend\public\data\ ; copy ..\data\meta.json ..\frontend\public\data\ ; copy ..\data\wells.json ..\frontend\public\data\
copy ..\data\zones.json ..\backend\data\ ; copy ..\data\meta.json ..\backend\data\ ; copy ..\data\wells.json ..\backend\data\
```

## 2. Priority score 0-100 + map  ✅ (groundwater factors only until step 3)
Score = XGBoost + inverse-distance blend, validated on unseen wells (R² ≈ 0.26: modest, say so). 4,618 zones (2 km), tiers High (top 20%) / Medium / Low.
Screen: **Map & zone**. Pins coloured by tier, faded by data confidence, wells shown as ◆.

## 3. Rainfall, soil, slope, structures, demand  🔧 (no local install: use Google Colab)
Four blueprint factors are empty until you run ONE script in Google Colab (free, normal internet):
1. Open https://colab.research.google.com -> New notebook.
2. Left panel (folder icon) -> upload `analysis/colab_extras.py` and `data/zones.json`  (both are also in colab-kit.zip).
3. In a cell run `!pip -q install rasterio scipy requests pandas numpy`, then in another cell `!python colab_extras.py` (10-25 min; rainfall download is the slow part).
4. Download `extra_features.csv` from the Files panel.
5. Put it in `data/extra_features.csv` and run `python score_pune.py --src <wells csv>` from `analysis/`, copy the 3 JSON files into `frontend/public/data` and `backend/data`, rebuild. (Or hand `extra_features.csv` to your AI assistant and ask it to do steps 5.)
Layers: CHIRPS rainfall (Jun-Sep mean 2014-2023), SoilGrids sand/clay -> infiltration 0-1, Copernicus DEM -> mean slope, OpenStreetMap water structures within 2.5 km, ESA WorldCover cropland + built-up share -> **water-demand PROXY** (not CGWB extraction data; say so).
If a layer fails the script still saves the others; missing factors are skipped and weights renormalised. The raster maths was tested on synthetic data; the live downloads were not tested from this build.

## 4. Location details + factor breakdown  ✅
Score, rank, per-factor input (0-100), weight and points contributed (blueprint section 8 style), measured depth/trend/recovery, distance to nearest well.

## 5. Intervention recommendation  ✅ (⚠️ rule-based)
Five types: Check Dam, Percolation Tank, Recharge Well, Farm Pond, Recharge Pit (rules use soil and rainfall relative to the study area, slope, depth, decline, recovery). Suitability rules in `backend/engine.py` and `frontend/src/lib.js` (identical). Each recommendation lists reasons. Uses soil/slope automatically when step 3 is done.

## 6. Budget optimization  ✅ (⚠️ illustrative costs)
Greedy by benefit per rupee, one project per zone, >=3 km spacing, no intervention type over 45% of budget (then a fill pass). Edit costs/benefits in `TYPES` (both files) when you have local estimates.

## 7. What-if + scenario comparison  ✅
Screen **Budget & what-if**: sliders for budget, rainfall, extraction; before/after totals, projects changed, changed priority scores.
Screen **Scenarios**: Baseline / Budget constrained / Rainfall -20% / Extraction -15% side by side with chart.
Assumption: extraction scales stress, rainfall scales recharge potential (elasticity 0.5). State this.

## 8. Impact summary  ✅
Budget utilization, projects, benefit, share in High-priority zones, mix chart, project list, **Print / save as PDF** button.

## 9. AI assistant  ✅ offline rules · 🔧 Strands agent after deploy
Offline: a rule assistant with ~12 question types (zone explain/compare, suitability, plans with budget+rain+extraction, filters like "top 5 deepest", scenarios, method, accuracy, costs, stats). Open-ended questions (definitions, how-to, map legend, data, limits, next steps) are answered from a built-in knowledge base with fuzzy matching; the Strands agent adds free-form LLM answers once deployed. Online: `backend/agent/agent.py` Strands agent with 7 tools (top_zones, explain_zone, optimize_budget, compare_scenarios, dataset_summary, find_zones, intervention_costs) and a no-invention guardrail prompt.
Needs Bedrock model access in your AWS region (Bedrock console -> Model access). Not tested against live Bedrock in this build.

## 10. AWS backend  🔧  (not deployed in this package)
```powershell
cd backend
sam build ; sam deploy --guided      # creates HTTP API, Lambda, DynamoDB table, S3 bucket
# upload data (deploy.sh does this on Linux/macOS/WSL):
aws s3 cp ..\data\zones.json s3://<DataBucketName>/processed/zones.json   # same for meta.json, wells.json
```
Copy the `ApiUrl` output into `frontend/.env` as `VITE_API_URL=...`, restart `npm run dev`. The header badge turns green ("AWS API connected"), the assistant uses the Strands agent, and "Save plan to AWS" writes to DynamoDB.
Routes: GET /health /meta /zones /zones/{id} /plans · POST /optimize /scenarios /agent. Local test without AWS: see `backend/handler.py` (all routes pass a local smoke test).
Logs: CloudWatch automatically (one JSON line per request). Cognito auth: optional, not included.
Notes: HTTP API times out at 30 s; if the agent is slow, raise Lambda memory or switch the agent to Function URL streaming. strands-agents is large, so build with `sam build --use-container` if the zip is too big.

## 11. Hosting  🔧
Amplify Hosting: push the repo to GitHub, connect `frontend/` (build settings in `frontend/amplify.yml`), add env var `VITE_API_URL`.
Or: `npm run build` and upload `frontend/dist` to S3 + CloudFront.

## 12. Demo + docs  ✅ / 🔧
`docs/DEMO_SCRIPT.md` (3 minutes), `docs/ARCHITECTURE.md`, `docs/ASSUMPTIONS.md`, `docs/CHECKLIST.md`. Take screenshots/video into `demo/` (blueprint section 25 asks for backup evidence).
- Every zone has lat/lon (cell centre): data/zones.json and data/scored_zones_pune.csv; the dashboard shows them with a Google Maps link.
