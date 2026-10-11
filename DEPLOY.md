# Deploy guide (Netlify + AWS)

## 1. Netlify (offline demo – ready now)
```bash
cd frontend
npm install
npm run build
# drag the `dist` folder to Netlify, or:
# netlify deploy --prod --dir=dist
```
The site runs in **Offline demo mode** (badge top-right). All scoring, budget optimizer, what-if, impact and assistant work without AWS.

## 2. AWS (backend + Strands agent)
```bash
cd backend
# requires AWS CLI + SAM CLI + Docker (or --use-container)
./deploy.sh
# or:
sam build && sam deploy --guided
# then upload data (deploy.sh does this) and set:
# frontend/.env  →  VITE_API_URL=https://xxxx.execute-api.region.amazonaws.com
# rebuild frontend and redeploy to Netlify
```

## Fixes applied in this version
- Area label: "Pune district" → "Pune region, Maharashtra"
- Zone IDs: stable grid-based `G######` (no longer reshuffle on rescore)
- Architecture diagram: `docs/architecture.svg` + updated ARCHITECTURE.md
- Agent / assistant examples updated for new IDs
