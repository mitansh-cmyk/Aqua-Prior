#!/usr/bin/env python3
"""colab_extras.py - ONE script that downloads the missing score layers for every AquaPrior zone and writes extra_features.csv.
Run it in Google Colab (free, no install on your PC):
    1) colab.research.google.com -> New notebook.   2) Files panel (left) -> upload this file AND zones.json (from the data folder).
    3) In a cell:   !pip -q install rasterio scipy requests pandas numpy       then new cell:   !python colab_extras.py
    4) Download extra_features.csv from the Files panel (takes ~10-25 min; CHIRPS is the slow part).
Layers (each is optional - if one fails the others are still written):
  rain_monsoon_mm   CHIRPS v2 monthly rainfall, Jun-Sep summed, mean of years      (data.chc.ucsb.edu)
  soil_infil_score  SoilGrids sand/clay 0-30 cm -> 0..1 infiltration suitability    (files.isric.org)
  slope_mean_deg    Copernicus GLO-30 DEM -> mean slope in a 2 km window            (AWS open data)
  struct_count      OpenStreetMap dams/weirs/ponds/reservoirs/water bodies within 2.5 km   (Overpass)
  demand_proxy      ESA WorldCover 2021: 0.7*cropland share + 0.3*built-up share in 2 km   (AWS open data)
NOTE demand_proxy is a PROXY for water demand (irrigation + settlement pressure), not CGWB extraction data.
"""
import gzip, json, math, shutil, sys, time
from pathlib import Path
import numpy as np, pandas as pd, requests

BBOX = (73.30, 18.00, 74.90, 19.20)          # lon0 lat0 lon1 lat1 (same as score_pune.py)
YEARS = (2014, 2023)
WORK = Path("work"); WORK.mkdir(exist_ok=True)

def grid_for(bbox, res):
    w, s, e, n = bbox; return int(round((e - w) / res)), int(round((n - s) / res))

def read_on_grid(path, bbox, res, resampling="nearest", band=1):
    """Read any raster (URL or file) onto a regular lon/lat grid covering bbox. Returns float array (rows=north->south), NaN=nodata."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.vrt import WarpedVRT
    W, H = grid_for(bbox, res); tr = from_origin(bbox[0], bbox[3], res, res)
    with rasterio.open(path) as src:
        with WarpedVRT(src, crs="EPSG:4326", transform=tr, width=W, height=H, resampling=getattr(Resampling, resampling)) as v:
            a = v.read(band, masked=True).astype("float32").filled(np.nan)
    return a

def sample(arr, bbox, res, lon, lat, smooth_px=1):
    """Value at points; optionally a box-mean over smooth_px pixels (NaN-aware)."""
    from scipy.ndimage import uniform_filter, map_coordinates
    a = arr.copy(); m = np.isfinite(a); a[~m] = 0
    if smooth_px > 1:
        num = uniform_filter(a, smooth_px, mode="nearest"); den = uniform_filter(m.astype("float32"), smooth_px, mode="nearest")
        a = np.where(den > 0.05, num / np.maximum(den, 1e-6), np.nan)
    else:
        a = np.where(m, a, np.nan)
    c = (np.asarray(lon) - bbox[0]) / res - 0.5; r = (bbox[3] - np.asarray(lat)) / res - 0.5
    out = map_coordinates(np.nan_to_num(a, nan=-9e9), [r, c], order=1, mode="nearest")
    return np.where(out < -1e9, np.nan, out)

def slope_deg(dem, res):
    lat0 = math.radians((BBOX[1] + BBOX[3]) / 2); dx = res * 111320 * math.cos(lat0); dy = res * 110574
    gy, gx = np.gradient(dem, dy, dx); return np.degrees(np.arctan(np.hypot(gx, gy)))

def dl(url, dest, tries=3):
    if dest.exists() and dest.stat().st_size > 0: return dest
    for k in range(tries):
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for c in r.iter_content(1 << 20): f.write(c)
            return dest
        except Exception as ex: print("  retry", k + 1, url.split("/")[-1], ex); time.sleep(3 * (k + 1))
    raise RuntimeError("download failed: " + url)

# ---------------- layers ----------------
def layer_rain(lon, lat):
    res = 0.05; ys = range(YEARS[0], YEARS[1] + 1); tot = []
    for y in ys:
        s = None
        for m in (6, 7, 8, 9):
            gz = WORK / f"chirps.{y}.{m:02d}.tif.gz"; tif = gz.with_suffix("")
            if not tif.exists():
                dl(f"https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/tifs/chirps-v2.0.{y}.{m:02d}.tif.gz", gz)
                with gzip.open(gz, "rb") as fi, open(tif, "wb") as fo: shutil.copyfileobj(fi, fo)
                gz.unlink()
            a = read_on_grid(str(tif), (BBOX[0] - .1, BBOX[1] - .1, BBOX[2] + .1, BBOX[3] + .1), res, "bilinear")
            a[a < 0] = np.nan; s = a if s is None else s + a
        tot.append(s); print("  rain", y, "ok")
    mean = np.nanmean(np.stack(tot), 0); b = (BBOX[0] - .1, BBOX[1] - .1, BBOX[2] + .1, BBOX[3] + .1)
    return sample(mean, b, res, lon, lat)

def layer_soil(lon, lat):
    res = 0.0025; base = "https://files.isric.org/soilgrids/latest/data"; out = {}
    for prop in ("sand", "clay"):
        acc = []
        for d in ("0-5cm", "5-15cm", "15-30cm"):
            a = read_on_grid(f"{base}/{prop}/{prop}_{d}_mean.vrt", BBOX, res, "bilinear"); acc.append(a)
        m = np.nanmean(np.stack(acc), 0); out[prop] = m / 10.0 if np.nanmedian(m) > 100 else m    # g/kg -> %
        print("  soil", prop, "ok")
    infil = np.clip(0.5 + (out["sand"] - out["clay"]) / 100.0, 0, 1)       # sandy = permeable, clayey = not
    return sample(infil, BBOX, res, lon, lat, smooth_px=7)

def layer_slope(lon, lat):
    res = 0.001; tiles = set()
    for la in range(int(math.floor(BBOX[1])), int(math.floor(BBOX[3])) + 1):
        for lo in range(int(math.floor(BBOX[0])), int(math.floor(BBOX[2])) + 1): tiles.add((la, lo))
    dem = None
    for la, lo in sorted(tiles):
        n = f"Copernicus_DSM_COG_10_N{la:02d}_00_E{lo:03d}_00_DEM"
        try: a = read_on_grid(f"https://copernicus-dem-30m.s3.amazonaws.com/{n}/{n}.tif", BBOX, res, "bilinear")
        except Exception as ex: print("  DEM tile", n, "skipped:", ex); continue
        dem = a if dem is None else np.where(np.isfinite(dem), dem, a)
    if dem is None: raise RuntimeError("no DEM tiles")
    sl = slope_deg(np.nan_to_num(dem, nan=float(np.nanmedian(dem))), res); print("  slope ok")
    return sample(sl, BBOX, res, lon, lat, smooth_px=17)

def layer_osm(lon, lat):
    URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
    seen, pts = set(), []; step = 0.4
    for s in np.arange(BBOX[1], BBOX[3], step):
        for w in np.arange(BBOX[0], BBOX[2], step):
            bb = f"({s},{w},{min(s + step, BBOX[3])},{min(w + step, BBOX[2])})"
            q = f'[out:json][timeout:120];(nwr["waterway"~"^(dam|weir)$"]{bb};nwr["natural"="water"]{bb};nwr["landuse"="reservoir"]{bb};nwr["water"~"^(pond|reservoir|lake|basin)$"]{bb};);out center;'
            for u in URLS:
                try:
                    r = requests.post(u, data={"data": q}, timeout=180, headers={"User-Agent": "aquaprior/1.0"}); r.raise_for_status()
                    for el in r.json()["elements"]:
                        k = (el["type"], el["id"]); la = el.get("lat", el.get("center", {}).get("lat")); lo = el.get("lon", el.get("center", {}).get("lon"))
                        if k not in seen and la is not None: seen.add(k); pts.append((la, lo))
                    break
                except Exception as ex: print("  overpass retry:", ex); time.sleep(10)
            print("  osm tile", round(s, 1), round(w, 1), "total", len(pts)); time.sleep(2)
    if not pts: raise RuntimeError("no OSM features returned")
    from scipy.spatial import cKDTree
    kx = 111 * math.cos(math.radians(18.6)); T = cKDTree(np.c_[[p[1] * kx for p in pts], [p[0] * 111 for p in pts]])
    return np.array([len(x) for x in T.query_ball_point(np.c_[np.asarray(lon) * kx, np.asarray(lat) * 111], 2.5)], dtype=float)

def layer_demand(lon, lat):
    res = 0.002; la = int(math.floor(BBOX[1] / 3) * 3); lo = int(math.floor(BBOX[0] / 3) * 3)
    a = read_on_grid(f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N{la:02d}E{lo:03d}_Map.tif", BBOX, res, "nearest")
    crop = np.where(np.isfinite(a), (a == 40).astype("float32"), np.nan); built = np.where(np.isfinite(a), (a == 50).astype("float32"), np.nan)
    print("  landcover ok")
    return 0.7 * sample(crop, BBOX, res, lon, lat, smooth_px=9) + 0.3 * sample(built, BBOX, res, lon, lat, smooth_px=9)

LAYERS = [("rain_monsoon_mm", layer_rain), ("soil_infil_score", layer_soil), ("slope_mean_deg", layer_slope), ("struct_count", layer_osm), ("demand_proxy", layer_demand)]

def main():
    z = json.loads(Path("zones.json").read_text()); lat = np.array([q["lat"] for q in z]); lon = np.array([q["lon"] for q in z])
    df = pd.DataFrame({"lat": lat, "lon": lon}); print(len(df), "zone points")
    for name, fn in LAYERS:
        print("==", name)
        try: df[name] = fn(lon, lat); print("  ", name, "ok:", int(df[name].notna().sum()), "values, range", round(float(np.nanmin(df[name])), 2), "-", round(float(np.nanmax(df[name])), 2))
        except Exception as ex: print("  !! FAILED:", ex)
        df.to_csv("extra_features.csv", index=False)       # save after every layer
    print("\nSUMMARY"); print(df.describe().T[["count", "min", "mean", "max"]].round(2).to_string()); print("\nDownload extra_features.csv from the Files panel.")

if __name__ == "__main__": main()
