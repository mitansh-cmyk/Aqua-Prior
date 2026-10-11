# Architecture

![AquaPrior AWS Architecture](architecture.svg)

```
Browser (React + Leaflet)  --HTTPS-->  API Gateway (HTTP API)  -->  Lambda (backend/handler.py)
   |  offline fallback: lib.js engine                                  |-- engine.py (score lookup, optimize, what-if)
   |                                                                   |-- agent/agent.py  (Strands Agent + tools -> Bedrock)
   |                                                                   |-- S3  processed/{zones,meta,wells}.json (read)
   |                                                                   '-- DynamoDB  saved plans (write/scan)
analysis/ (run offline): India-WRIS CSV -> score_pune.py -> data/*.json -> upload to S3
```

Why this is small on purpose: Lambda + API Gateway + S3 + DynamoDB + Strands/Bedrock all do real work. No SageMaker: the ML is a small XGBoost trained offline on 145 wells.

`engine.py` (server) and `lib.js` (browser) implement identical rules; parity was checked on four budget/scenario cases.

## Deploy (AWS)

```bash
cd backend
# 1. Build + deploy SAM stack
sam build
sam deploy --guided   # or use deploy.sh

# 2. Upload data to the created S3 bucket
aws s3 cp data/zones.json s3://$BUCKET/processed/zones.json
aws s3 cp data/wells.json s3://$BUCKET/processed/wells.json
aws s3 cp data/meta.json  s3://$BUCKET/processed/meta.json

# 3. Point the frontend at the API
#    frontend/.env  →  VITE_API_URL=https://xxxx.execute-api.region.amazonaws.com
```

See `backend/deploy.sh` and `backend/template.yaml` for the full SAM definition.
