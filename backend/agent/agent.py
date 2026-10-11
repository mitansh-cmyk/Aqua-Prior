"""AI explanation agent (blueprint section 12). Uses AWS Strands Agents SDK when available, with a deterministic
rule-based fallback so the demo never breaks (no Bedrock access / cold SDK / offline).
Guardrail: the agent may only report numbers returned by the engine tools below."""
import json, os, re
import engine

SYSTEM = ("You are the AquaPrior groundwater-recharge decision assistant for Pune. Answer ONLY with values returned by your tools. "
          "Never invent measurements. Costs and benefits are illustrative assumptions; scores rank relative priority and do not "
          "predict groundwater levels. State assumptions briefly. Keep answers under 120 words.")

def top_zones(n: int = 3) -> str:
    """Return the n highest-priority zones with score, tier and recommended intervention."""
    return json.dumps([{**{k: z[k] for k in ("id", "score", "tier", "rank")}, "recommended": engine.recommend(z)} for z in engine.zones()[:int(n)]])

def explain_zone(zone_id: str) -> str:
    """Explain one zone: score, rank, factor breakdown, recommended intervention, cost, benefit and reasons."""
    d = engine.zone_detail(zone_id); return json.dumps(d) if d else "unknown zone"

def optimize_budget(budget_lakh: float, rain_change_pct: float = 0, extraction_change_pct: float = 0) -> str:
    """Select the best project mix for a budget in Rs lakh under optional rainfall/extraction scenario changes (percent)."""
    r = engine.optimize(float(budget_lakh), float(rain_change_pct), float(extraction_change_pct)); r["projects"] = r["projects"][:8]; return json.dumps(r)

def compare_scenarios(budget_lakh: float = 20) -> str:
    """Compare baseline, half budget, rainfall -20% and extraction -15% scenarios."""
    b = float(budget_lakh)
    return json.dumps([{k: r[k] for k in ("name", "n", "cost", "benefit", "delta_vs_first")} for r in engine.compare(
        [{"name": "Baseline", "budget": b}, {"name": "Budget constrained", "budget": b / 2},
         {"name": "Rainfall -20%", "budget": b, "rain": -20}, {"name": "Extraction -15%", "budget": b, "extraction": -15}])])

def dataset_summary() -> str:
    """Counts by tier, wells used, average depth/decline, validation R2, score weights and which factors have data."""
    return json.dumps(engine.summary())

def find_zones(tier: str = "", intervention: str = "", sort_by: str = "score", n: int = 5) -> str:
    """List zones filtered by tier (High/Medium/Low) and/or recommended intervention, sorted by score, depth, decline, rise or conf."""
    return json.dumps(engine.find_zones(tier or None, intervention or None, sort_by, n))

def intervention_costs() -> str:
    """Illustrative cost (Rs lakh) and base benefit units for each intervention type."""
    return json.dumps({k: {"cost_lakh": v[0], "base_benefit": v[1]} for k, v in engine.TYPES.items()})

FUNCS = [top_zones, explain_zone, optimize_budget, compare_scenarios, dataset_summary, find_zones, intervention_costs]

def rule_agent(q: str) -> str:
    x = q.lower(); zid = re.search(r"g\d{6}", x); L = re.search(r"(\d+(?:\.\d+)?)\s*(lakh|l\b)", x); R = re.search(r"rain\w*\s*(?:by|to|of)?\s*([+-]?\d+)", x)
    if "compar" in x and not zid: return "Scenario comparison (₹20L base): " + compare_scenarios(20)
    if zid:
        d = engine.zone_detail(zid.group()); 
        return "Unknown zone." if not d else (f"{d['id']} is ranked #{d['rank']} (score {d['score']}, {d['tier']}). Drivers: {', '.join(d['reasons'])}. "
                f"Suggested {d['recommended']} (₹{d['cost']}L, rule-based suitability {round(d['suitability']*100)}%).")
    if L or R:
        r = engine.optimize(float(L.group(1)) if L else 20, float(R.group(1)) if R else 0)
        return (f"₹{r['budget']:g}L, rainfall {r['rain']:+g}%: {r['n']} projects, spend ₹{r['cost']}L, est. benefit {r['benefit']} (illustrative). "
                f"Mix: {r['mix']}. First: " + "; ".join(f"{p['intervention']} at {p['zone']}" for p in r['projects'][:3]))
    if re.search(r"top|prioriti|first|which", x): return "Top zones: " + top_zones(3)
    if re.search(r"how many|count|average|dataset|wells|stat", x): return "Dataset: " + dataset_summary()
    if re.search(r"cost|price", x): return "Costs: " + intervention_costs()
    return 'Try: "why is G047049 ranked #1?", "I have 10 lakh", "rainfall -20%", "compare scenarios", "how many high priority zones". Open-ended questions are answered by the Strands agent when Bedrock is enabled.'

_agent = None
def ask(question: str) -> dict:
    global _agent
    if os.environ.get("USE_STRANDS", "true").lower() == "true":
        try:
            from strands import Agent, tool
            if _agent is None:
                kw = {}
                if os.environ.get("BEDROCK_MODEL_ID"):
                    from strands.models import BedrockModel; kw["model"] = BedrockModel(model_id=os.environ["BEDROCK_MODEL_ID"])
                _agent = Agent(system_prompt=SYSTEM, tools=[tool(f) for f in FUNCS], **kw)
            return {"answer": str(_agent(question)), "engine": "strands"}
        except Exception as ex:  # fall back, but say so
            return {"answer": rule_agent(question), "engine": "rules", "note": f"Strands unavailable: {type(ex).__name__}"}
    return {"answer": rule_agent(question), "engine": "rules"}
