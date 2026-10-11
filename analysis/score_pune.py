#!/usr/bin/env python3
"""STEP 3 of the pipeline. Real-data priority scoring for Pune region from the India-WRIS manual groundwater file.
Pipeline: wells -> per-well stress metrics -> leave-one-well-out neighbour features
-> XGBoost (validated by leave-one-well-out CV) -> prediction on a 2 km grid -> frontend JSON.
Usage: python score_pune.py [--src groundwater-level-collected-manually.csv]  (or reuses pune_raw.pkl)"""
import argparse, json, math
from pathlib import Path
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
from sklearn.model_selection import KFold
from sklearn.metrics import r2_score, mean_absolute_error
import xgboost as xgb

BBOX = (73.30, 18.00, 74.90, 19.20)      # lon0 lat0 lon1 lat1
CELL_KM, MAX_WELL_KM, Y0, Y1 = 2.0, 12.0, 2009, 2023
PRE, POST = [3, 4, 5], [10, 11, 12]
ap = argparse.ArgumentParser(); ap.add_argument("--src"); a = ap.parse_args()
if a.src:
    cols = ["station_name","station_code","latitude","longitude","date","data_type_code","data_value","station_type"]
    df = pd.concat(c[(c.data_type_code=="HGZ") & c.longitude.between(73.0,75.4) & c.latitude.between(17.6,19.3)]
                   for c in pd.read_csv(a.src, usecols=cols, dtype={"station_code": str}, chunksize=500000, low_memory=False))
else:
    df = pd.read_pickle("pune_raw.pkl")
df["date"] = pd.to_datetime(df["date"], errors="coerce"); df["lvl"] = pd.to_numeric(df["data_value"], errors="coerce")
df = df.dropna(subset=["date","lvl"]); df = df[(df.lvl.between(-5,80)) & df.date.dt.year.between(Y0,Y1)]
df["y"], df["m"] = df.date.dt.year, df.date.dt.month

# ---- per-well metrics (all real measurements) ------------------------------
rows = []
for code, g in df.groupby("station_code"):
    pre = g[g.m.isin(PRE)].groupby("y").lvl.mean(); post = g[g.m.isin(POST)].groupby("y").lvl.mean()
    if len(pre) < 6: continue
    slope = np.polyfit(pre.index, pre.values, 1)[0]                    # +m/yr = water table deepening
    both = pd.concat([pre, post], axis=1, keys=["pre","post"]).dropna()
    rise = (both.pre - both.post).mean() if len(both) >= 4 else np.nan   # seasonal recovery after monsoon
    rows.append(dict(well_id=code, name=g.station_name.iloc[0], lat=g.latitude.iloc[0], lon=g.longitude.iloc[0],
                     depth=pre[pre.index >= pre.index.max()-4].mean(), decline=slope, rise=rise,
                     pre_years=len(pre), last_year=int(pre.index.max())))
W = pd.DataFrame(rows).dropna(subset=["lat","lon"]); W["rise"] = W.rise.fillna(W.rise.median())
W = W[(W.depth > 0)]
print(f"usable wells: {len(W)}  (>=6 pre-monsoon years, {Y0}-{Y1})")

def nrm(s, lo=None, hi=None):
    lo = s.quantile(.05) if lo is None else lo; hi = s.quantile(.95) if hi is None else hi
    return ((s - lo) / (hi - lo)).clip(0, 1)
# transparent per-well priority: stress (depth + decline) with seasonal-recovery opportunity
W["stress"] = .45*nrm(W.depth) + .55*nrm(W.decline.clip(lower=0))
W["opportunity"] = nrm(W.rise)
W["priority_obs"] = 100*(.60*W.stress + .40*W.opportunity)   # blueprint weights 30:20 renormalised

kx = 111.0*math.cos(math.radians(18.6)); XY = lambda lat, lon: np.c_[lon*kx, lat*111.0]
def feats(lat, lon, exclude_self=False, K=15):
    tree = cKDTree(XY(W.lat.values, W.lon.values))
    d, i = tree.query(XY(lat, lon), k=K+int(exclude_self))
    if exclude_self: d, i = d[:,1:], i[:,1:]
    wgt = 1/np.maximum(d, .5)**2; wgt /= wgt.sum(1, keepdims=True)
    f = {c: (W[c].values[i]*wgt).sum(1) for c in ["depth","decline","rise","priority_obs","stress","opportunity"]}
    f["d_near"] = d[:,0]; f["n_15km"] = (d < 15).sum(1); f["prio_sd"] = W.priority_obs.values[i].std(1)
    f["lat"], f["lon"] = lat, lon
    return pd.DataFrame(f)
FC = ["depth","decline","rise","priority_obs","d_near","n_15km","prio_sd","lat","lon"]

# ---- validation: leave-one-well-out features, 5-fold CV --------------------
Xw = feats(W.lat.values, W.lon.values, exclude_self=True); yw = W.priority_obs.values
mk = lambda: xgb.XGBRegressor(n_estimators=150, max_depth=2, learning_rate=.05, subsample=.8, min_child_weight=5, random_state=7)
pred = np.zeros(len(W))
for tr, te in KFold(5, shuffle=True, random_state=7).split(Xw):
    pred[te] = mk().fit(Xw.iloc[tr][FC], yw[tr]).predict(Xw.iloc[te][FC])
idw = Xw.priority_obs.values
bl = (pred + idw)/2     # final score = 50% XGBoost + 50% inverse-distance interpolation (best under CV)
metrics = dict(n_wells=len(W), xgb_r2=round(r2_score(yw,pred),3), idw_r2=round(r2_score(yw,idw),3),
               final_r2=round(r2_score(yw,bl),3), final_mae=round(mean_absolute_error(yw,bl),2))
print("CV (unseen wells):", metrics)
model = mk().fit(Xw[FC], yw)
imp = dict(zip(FC, map(float, model.feature_importances_)))

# ---- grid prediction ---------------------------------------------------------
dlat = CELL_KM/111.0; dlon = CELL_KM/kx
lats = np.arange(BBOX[1]+dlat/2, BBOX[3], dlat); lons = np.arange(BBOX[0]+dlon/2, BBOX[2], dlon)
G = pd.DataFrame([(a_, b_) for a_ in lats for b_ in lons], columns=["lat","lon"])
F = feats(G.lat.values, G.lon.values); keep = (F.d_near <= MAX_WELL_KM).values
G, F = G[keep].reset_index(drop=True), F[keep].reset_index(drop=True)
G["gw_comp"] = np.clip((model.predict(F[FC]) + F.priority_obs.values)/2, 0, 100)   # groundwater part (stress + recharge response)
G["stress"], G["recharge"] = F.stress.clip(0,1), F.opportunity.clip(0,1)
G["depth"], G["decline"], G["rise"], G["d_near"], G["n15"] = F.depth, F.decline, F.rise, F.d_near, F.n_15km
G["conf"] = np.clip(1 - F.d_near/MAX_WELL_KM, 0, 1)*.6 + np.clip(F.n_15km/6, 0, 1)*.4

# ---- OPTIONAL extra factors from your own build_features.py run (data/extra_features.csv) ----
# Blueprint weights. Factors with no data are skipped and the remaining weights are renormalised per cell.
WTS = dict(sr=.50, rain=.15, soil=.15, demand=.10, gap=.10)   # sr = stress(.30)+recharge(.20) from wells
EX = Path("../data/extra_features.csv"); DEMAND_PROXY = False
for c in ["rain","soil","slope","struct","stage"]: G[c] = np.nan
if EX.exists():
    e = pd.read_csv(EX)
    # ---- sanitise: nodata sentinels / impossible values -> NaN -> filled from the nearest valid cell (reported below) ----
    VALID = {"rain_monsoon_mm": (100, 6000), "soil_infil_score": (0, 1), "slope_mean_deg": (0, 60), "struct_count": (0, 5000), "demand_proxy": (0, 1), "stage_pct": (0, 300)}
    for col, (lo, hi) in VALID.items():
        if col not in e.columns: continue
        bad = ~e[col].between(lo, hi); n_bad = int(bad.sum())
        if n_bad and n_bad < len(e):
            ok_ = ~bad; tr = cKDTree(XY(e.lat.values[ok_], e.lon.values[ok_])); _, j = tr.query(XY(e.lat.values[bad], e.lon.values[bad]))
            e.loc[bad, col] = e[col].values[ok_][j]
        print(f"  cleaned {col}: {n_bad} invalid/missing values replaced by nearest valid neighbour")
    t = cKDTree(XY(e.lat.values, e.lon.values)); d, i = t.query(XY(G.lat.values, G.lon.values))
    ok = d <= 1.5*CELL_KM
    m = {"rain": "rain_monsoon_mm", "soil": "soil_infil_score", "slope": "slope_mean_deg", "struct": "struct_count", "stage": "stage_pct"}
    for k, col in m.items():
        if col in e.columns: G.loc[ok, k] = e[col].values[i[ok]]
    if "stage_pct" not in e.columns and "demand_proxy" in e.columns:      # colab_extras.py: cropland + built-up share as demand PROXY
        G.loc[ok, "stage"] = e["demand_proxy"].values[i[ok]]; DEMAND_PROXY = True
    print("extra features merged:", {k: int(G[k].notna().sum()) for k in m})
else:
    print("No data/extra_features.csv -> score uses groundwater factors only (see docs/FEATURES.md step 3)")
nz = lambda s: nrm(s) if s.notna().sum() > 10 else s
fac = dict(rain=nz(G.rain), soil=nz(G.soil), demand=nz(G.stage), gap=1-nz(G.struct))
num = WTS["sr"]*G.gw_comp/100; den = pd.Series(WTS["sr"], index=G.index)
for k, v in fac.items():
    num = num + (WTS[k]*v).fillna(0); den = den + WTS[k]*v.notna()
G["score"] = np.clip(100*num/den, 0, 100)
G["rank"] = G.score.rank(ascending=False, method="min").astype(int)
q80, q50 = G.score.quantile(.8), G.score.quantile(.5)
G["tier"] = np.where(G.score >= q80, "High", np.where(G.score >= q50, "Medium", "Low"))
G = G.sort_values("rank")
print(G.tier.value_counts().to_dict(), f"cells={len(G)}  top={G.score.max():.1f}")

R = lambda v, n=2: None if pd.isna(v) else round(float(v), n)
# Stable grid IDs from lat/lon so re-scoring does not reshuffle codes
DEG_LON = CELL_KM / 111.32 / math.cos(math.radians((BBOX[1]+BBOX[3])/2))
DEG_LAT = CELL_KM / 110.57
def _sid(lat, lon):
    i = int(round((lon - BBOX[0]) / DEG_LON)); j = int(round((lat - BBOX[1]) / DEG_LAT))
    return f"G{i:03d}{j:03d}"
zones = [dict(id=_sid(r.lat, r.lon), lat=round(r.lat,4), lon=round(r.lon,4), score=round(r.score,1), rank=int(r.rank), tier=r.tier,
              depth=round(r.depth,1), decline=round(r.decline,2), rise=round(r.rise,1), conf=round(r.conf,2), nearKm=round(r.d_near,1),
              stress=R(r.stress), recharge=R(r.recharge), rain=R(r.rain,0), soil=R(r.soil), slope=R(r.slope,1),
              struct=R(r.struct,0), stage=R(r.stage,0))
         for r in G.itertuples()]
wells = [dict(id=r.well_id, name=r.name, lat=round(r.lat,4), lon=round(r.lon,4), depth=round(r.depth,1),
              decline=round(r.decline,2), years=int(r.pre_years), obs=round(r.priority_obs,1)) for r in W.itertuples()]
have = {k: bool(G[k].notna().any()) for k in ["rain","soil","slope","struct","stage"]}
meta = dict(demandIsProxy=DEMAND_PROXY, area="Pune region, Maharashtra", bbox=BBOX, cellKm=CELL_KM, years=[Y0,Y1], metrics=metrics, importance=imp,
            q80=round(q80,1), q50=round(q50,1), weights=dict(stress=.30, recharge=.20, rain=.15, soil=.15, demand=.10, gap=.10),
            factorsAvailable=dict(stress=True, recharge=True, rain=have["rain"], soil=have["soil"], demand=have["stage"], gap=have["struct"]),
            source="India-WRIS manual groundwater levels (HGZ, depth below ground)")
out = Path("../data"); out.mkdir(exist_ok=True)
for n, o in [("zones", zones), ("wells", wells), ("meta", meta)]:
    (out/f"{n}.json").write_text(json.dumps(o, separators=(",",":")))
G.to_csv(out/"scored_zones_pune.csv", index=False); W.to_csv(out/"wells_scored.csv", index=False)
print("wrote", len(zones), "zones,", len(wells), "wells ->", out.resolve())
