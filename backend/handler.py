"""API Gateway (HTTP API, payload v2) -> Lambda. Routes:
GET /health | GET /meta | GET /zones?tier=&limit= | GET /zones/{id} | POST /optimize | POST /scenarios | POST /agent | GET /plans"""
import json, logging, os, time, uuid
import engine
from agent.agent import ask

log = logging.getLogger(); log.setLevel(logging.INFO)
H = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
BUCKET, TABLE = os.environ.get("DATA_BUCKET"), os.environ.get("PLANS_TABLE")
_ready = False

def _boot():  # prefer processed data in S3 (so re-scoring needs no redeploy); fall back to bundled files
    global _ready
    if _ready: return
    if BUCKET:
        try:
            import boto3; s3 = boto3.client("s3")
            g = lambda k: json.loads(s3.get_object(Bucket=BUCKET, Key=f"processed/{k}.json")["Body"].read())
            engine.set_data(g("zones"), g("meta")); log.info("data loaded from s3://%s", BUCKET)
        except Exception as ex:
            log.warning("S3 load failed (%s); using bundled data", ex)
    _ready = True

def _resp(code, body): return {"statusCode": code, "headers": H, "body": json.dumps(body)}

def _save(item):
    if not TABLE: return False
    try:
        import boto3; from decimal import Decimal
        boto3.resource("dynamodb").Table(TABLE).put_item(Item=json.loads(json.dumps(item), parse_float=Decimal)); return True
    except Exception as ex: log.warning("DynamoDB save failed: %s", ex); return False

def lambda_handler(event, context):
    t0 = time.time(); _boot()
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET"); path = event.get("rawPath", "/")
    q = event.get("queryStringParameters") or {}
    try: body = json.loads(event.get("body") or "{}")
    except Exception: return _resp(400, {"error": "invalid JSON"})
    try:
        if method == "OPTIONS": return _resp(200, {})
        if path == "/health": return _resp(200, {"ok": True, "zones": len(engine.zones()), "s3": bool(BUCKET), "table": bool(TABLE)})
        if path == "/meta": return _resp(200, engine.meta())
        if path == "/zones":
            z = [z for z in engine.zones() if not q.get("tier") or z["tier"] == q["tier"]][: int(q.get("limit", 200))]
            return _resp(200, {"count": len(z), "zones": z})
        if path.startswith("/zones/"):
            d = engine.zone_detail(path.split("/")[-1]); return _resp(200, d) if d else _resp(404, {"error": "zone not found"})
        if path == "/optimize" and method == "POST":
            r = engine.optimize(float(body.get("budget", 20)), float(body.get("rain", 0)), float(body.get("extraction", 0)))
            if body.get("save"): r["id"] = str(uuid.uuid4()); r["saved"] = _save({"id": r["id"], "ts": int(time.time()), "plan": r})
            return _resp(200, r)
        if path == "/scenarios" and method == "POST":
            sc = body.get("scenarios") or [{"name": "Baseline", "budget": 20}, {"name": "Budget constrained", "budget": 10},
                                           {"name": "Rainfall shock", "budget": 20, "rain": -20}, {"name": "Demand reduction", "budget": 20, "extraction": -15}]
            return _resp(200, {"scenarios": engine.compare(sc)})
        if path == "/agent" and method == "POST": return _resp(200, ask(str(body.get("question", ""))[:500]))
        if path == "/plans":
            if not TABLE: return _resp(200, {"plans": []})
            import boto3; items = boto3.resource("dynamodb").Table(TABLE).scan(Limit=20).get("Items", [])
            return _resp(200, json.loads(json.dumps({"plans": items}, default=float)))
        return _resp(404, {"error": f"no route {method} {path}"})
    except Exception as ex:
        log.exception("handler error"); return _resp(500, {"error": str(ex)})
    finally:
        log.info(json.dumps({"path": path, "method": method, "ms": int((time.time() - t0) * 1000)}))
