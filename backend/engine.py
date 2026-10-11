"""Analysis engine: suitability, cost/benefit, budget optimizer, what-if. Pure Python, no AWS imports.
Mirrors frontend/src/lib.js (checked for identical output). Costs in Rs lakh; benefit in illustrative units."""
import json, math
from pathlib import Path

TYPES = {  # cost (Rs lakh), base benefit (illustrative units) -- REPLACE with verified local estimates
    "Check Dam": (8.5, 18.5), "Percolation Tank": (12.0, 24.8), "Recharge Well": (3.2, 12.2),
    "Farm Pond": (4.5, 14.1), "Recharge Pit": (1.5, 4.5),
}
clamp = lambda v, a=0.0, b=1.0: min(b, max(a, v))
_cache = {}

def load(name, base=None):
    base = Path(base or Path(__file__).parent / "data")
    if name not in _cache:
        _cache[name] = json.loads((base / f"{name}.json").read_text())
    return _cache[name]

def set_data(zones, meta):  # lets Lambda inject data fetched from S3
    _cache["zones"], _cache["meta"] = zones, meta

def zones(): return load("zones")
def meta(): return load("meta")

def _rel(k, v):
    """Position (0-1) inside this study area's 5th-95th percentile range; 0.5 when the layer is missing."""
    r = _norm(k, v); return 0.5 if r is None else r

def suitability(z, t):
    deep, dec, rise = clamp((z["depth"] - 3) / 15), clamp(z["decline"] / 0.8), clamp(z["rise"] / 6)
    soil, rain = _rel("soil", z.get("soil")), _rel("rain", z.get("rain"))
    slope = z.get("slope"); steep = 0.5 if slope is None else clamp(slope / 6)
    if t == "Recharge Well": return 0.3 + 0.7 * deep
    if t == "Percolation Tank": return 0.35 + 0.65 * (0.3 * rise + 0.2 * dec + 0.25 * soil + 0.25 * rain)
    if t == "Check Dam": return 0.35 + 0.65 * (0.35 * dec + 0.25 * rain + 0.25 * steep + 0.15 * (1 - deep))
    if t == "Recharge Pit": return 0.3 + 0.7 * (0.35 * (1 - deep) + 0.65 * soil) * 0.9
    return 0.45 + 0.2 * rise

def recommend(z):
    return max(TYPES, key=lambda t: (suitability(z, t), -list(TYPES).index(t)))

def reasons(z):
    r = []
    if z["decline"] > 0.3: r.append(f"water table falling {z['decline']:.2f} m/yr")
    if z["depth"] > 10: r.append(f"deep pre-monsoon water level ({z['depth']} m)")
    if z["rise"] > 3: r.append(f"strong post-monsoon recovery ({z['rise']} m)")
    if z.get("soil") is not None and z["soil"] > 0.6: r.append("permeable soil")
    if z.get("struct") == 0: r.append("no mapped recharge structures nearby")
    if z["conf"] < 0.4: r.append("low data confidence (far from wells)")
    return r or ["moderate signals on all measured factors"]

_rng = {}
def _norm(k, v):
    """0-1 normalisation using the 5th-95th percentile of the dataset (same rule as analysis/score_pune.py)."""
    if v is None: return None
    if k not in _rng:
        xs = sorted(z[k] for z in zones() if z.get(k) is not None)
        _rng[k] = (xs[int(.05 * (len(xs) - 1))], xs[int(.95 * (len(xs) - 1))]) if xs else (0, 1)
    lo, hi = _rng[k]; return clamp((v - lo) / (hi - lo)) if hi > lo else 0.5

def breakdown(z):
    """Per-factor 0-100 input, weight and share of the score (blueprint section 8). Missing factors are flagged, never invented."""
    W = meta()["weights"]
    raw = {"stress": z.get("stress"), "recharge": z.get("recharge"), "rain": _norm("rain", z.get("rain")),
           "soil": _norm("soil", z.get("soil")), "demand": _norm("stage", z.get("stage")),
           "gap": None if z.get("struct") is None else 1 - _norm("struct", z["struct"])}
    out = [{"factor": k, "weight": W[k], "value": None if raw[k] is None else round(raw[k] * 100), "available": raw[k] is not None} for k in W]
    tot = sum(o["weight"] * o["value"] for o in out if o["available"]) or 1
    for o in out: o["contribution"] = round(z["score"] * o["weight"] * o["value"] / tot, 1) if o["available"] else None
    return out

def adj_score(z, rain=0, ex=0):
    """What-if: extraction scales stress (x0.5 elasticity), rainfall scales recharge potential (x0.5). Documented assumptions."""
    W = meta()["weights"]; ws, wr = W["stress"], W["recharge"]
    ds = (z.get("stress") or 0) * 0.5 * ex / 100; dr = (z.get("recharge") or 0) * 0.5 * rain / 100
    return clamp(z["score"] + 100 * (ws * ds + wr * dr) / (ws + wr), 0, 100)

def benefit(z, t, rain=0, ex=0):
    return TYPES[t][1] * adj_score(z, rain, ex) / 100 * (1 + rain / 100) * (0.5 + suitability(z, t)) * (0.6 + 0.4 * z["conf"])

KX = 111 * math.cos(math.radians(18.6))

def optimize(budget, rain=0, ex=0, spacing_km=3.0, max_cand=600, cap=0.45):
    """Greedy by benefit per rupee; one project per cell; min spacing; no type > cap of budget."""
    c = []
    for z in zones()[:max_cand]:
        t = recommend(z); c.append((benefit(z, t, rain, ex) / TYPES[t][0], z, t))
    c.sort(key=lambda x: -x[0])
    rem, out, spent = budget, [], {}
    for lim in (cap, 1.0):                       # pass 1 keeps the portfolio diverse; pass 2 uses leftover budget
      for _, z, t in c:
        cost = TYPES[t][0]
        if cost > rem or spent.get(t, 0) + cost > lim * budget or any(o["zone"] == z["id"] for o in out): continue
        if any(math.hypot((o["lon"] - z["lon"]) * KX, (o["lat"] - z["lat"]) * 111) < spacing_km for o in out): continue
        out.append({"zone": z["id"], "lat": z["lat"], "lon": z["lon"], "intervention": t, "cost": cost,
                    "benefit": round(benefit(z, t, rain, ex), 2), "score": round(adj_score(z, rain, ex), 1),
                    "reasons": reasons(z)})
        rem -= cost; spent[t] = spent.get(t, 0) + cost
    return {"budget": budget, "rain": rain, "extraction": ex, "projects": out, "n": len(out),
            "cost": round(budget - rem, 2), "benefit": round(sum(p["benefit"] for p in out), 1),
            "mix": {t: sum(1 for p in out if p["intervention"] == t) for t in {p["intervention"] for p in out}}}

def compare(scenarios):
    base = None; res = []
    for s in scenarios:
        r = optimize(s.get("budget", 20), s.get("rain", 0), s.get("extraction", 0)); r["name"] = s.get("name", "scenario")
        base = base or r; r["delta_vs_first"] = round(r["benefit"] - base["benefit"], 1); res.append(r)
    return res

def zone_detail(zid):
    z = next((z for z in zones() if z["id"] == zid.upper()), None)
    if not z: return None
    t = recommend(z)
    return {**z, "recommended": t, "cost": TYPES[t][0], "benefit": round(benefit(z, t), 2),
            "suitability": round(suitability(z, t), 2), "reasons": reasons(z), "breakdown": breakdown(z)}

def summary():
    z = zones(); n = lambda t: sum(1 for x in z if x["tier"] == t)
    return {"zones": len(z), "high": n("High"), "medium": n("Medium"), "low": n("Low"),
            "avg_depth_m": round(sum(x["depth"] for x in z) / len(z), 2), "avg_decline_m_yr": round(sum(x["decline"] for x in z) / len(z), 3),
            "zones_deepening": sum(1 for x in z if x["decline"] > 0), "wells_used": meta()["metrics"]["n_wells"],
            "validation_r2": meta()["metrics"]["final_r2"], "factors_available": meta()["factorsAvailable"], "weights": meta()["weights"]}

def find_zones(tier=None, intervention=None, sort_by="score", n=5):
    """Filter zones by tier and/or recommended intervention; sort_by in score|depth|decline|rise|conf."""
    out = [z for z in zones() if (not tier or z["tier"].lower() == tier.lower()) and (not intervention or recommend(z).lower() == intervention.lower())]
    out.sort(key=lambda z: -z.get(sort_by, z["score"]))
    return [{"id": z["id"], "score": z["score"], "tier": z["tier"], "depth": z["depth"], "decline": z["decline"], "recommended": recommend(z)} for z in out[:int(n)]]
