#!/usr/bin/env python3
"""
Fetch water-conservation / water-body "structures" for your bbox WITHOUT any login.

Sources (both anonymous, run this on YOUR computer - my sandbox could not reach them):
  1. OpenStreetMap via Overpass: dams, weirs (check dams are often tagged weir/dam),
     ponds, reservoirs, other water bodies
  2. JRC Global Surface Water (occurrence layer, 30 m) from the public Google Cloud bucket:
     water bodies seen in >= --min-occ % of Landsat scenes, one point per water body

Output: data/raw/structures.csv   (columns: lat, lon, type, name, source, area_ha)
build_features.py picks up the FIRST file matching data/raw/structures.* - so keep
only this one file with that name.

Usage:
    pip install requests pandas numpy rasterio scipy
    python fetch_structures.py --bbox 74.06 18.10 74.26 18.30
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import requests

OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]


def osm_structures(bbox):
    w, s, e, n = bbox
    bb = f"({s},{w},{n},{e})"
    q = f"""[out:json][timeout:120];
(
  nwr["waterway"~"^(dam|weir)$"]{bb};
  nwr["natural"="water"]{bb};
  nwr["landuse"="reservoir"]{bb};
  nwr["water"~"^(pond|reservoir|lake|basin)$"]{bb};
);
out center tags;"""
    last = None
    for url in OVERPASS:
        try:
            r = requests.post(url, data={"data": q}, timeout=180,
                              headers={"User-Agent": "recharge-planner/1.0"})
            r.raise_for_status()
            elems = r.json()["elements"]
            break
        except Exception as ex:  # try next mirror
            last = ex
    else:
        raise RuntimeError(f"Overpass failed on all mirrors: {last}")

    rows = []
    for el in elems:
        t = el.get("tags", {})
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lon = el.get("lon", el.get("center", {}).get("lon"))
        if lat is None or lon is None:
            continue
        if t.get("waterway") == "dam":
            typ = "dam"
        elif t.get("waterway") == "weir":
            typ = "weir"
        elif t.get("water") in ("pond", "basin"):
            typ = "pond"
        elif t.get("landuse") == "reservoir" or t.get("water") == "reservoir":
            typ = "reservoir"
        else:
            typ = "water_body"
        rows.append(dict(lat=lat, lon=lon, type=typ, name=t.get("name", ""),
                         source="osm", area_ha=np.nan))
    print(f"OSM: {len(rows)} features")
    return pd.DataFrame(rows)


def jrc_waterbodies(bbox, min_occ=25, min_pixels=5):
    import rasterio
    from rasterio.windows import from_bounds
    from scipy import ndimage

    w, s, e, n = bbox
    # tile naming: occurrence_<west>E_<north>Nv1_4_2021.tif, 10-degree tiles
    lon0 = int(np.floor(w / 10) * 10)
    lat0 = int(np.ceil(n / 10) * 10)
    if np.floor(e / 10) * 10 != lon0 or np.ceil(s / 10) * 10 != lat0:
        print("JRC: bbox crosses a 10-degree tile edge - skipped (needs mosaicking)")
        return pd.DataFrame()
    url = ("https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/"
           f"occurrence_{lon0}E_{lat0}Nv1_4_2021.tif")
    with rasterio.open(url) as src:
        win = from_bounds(w, s, e, n, transform=src.transform)
        arr = src.read(1, window=win)
        tr = src.window_transform(win)
    mask = (arr >= min_occ) & (arr <= 100)          # 255 = no data
    lab, num = ndimage.label(mask)
    rows = []
    pix_ha = abs(tr.a * tr.e) * (111_320 ** 2) * np.cos(np.radians((s + n) / 2)) / 10_000
    for i in range(1, num + 1):
        m = lab == i
        cnt = int(m.sum())
        if cnt < min_pixels:
            continue
        r, c = ndimage.center_of_mass(m)
        lon, lat = tr * (c + 0.5, r + 0.5)
        rows.append(dict(lat=lat, lon=lon, type="jrc_water", name="", source="jrc",
                         area_ha=round(cnt * pix_ha, 2)))
    print(f"JRC: {len(rows)} water bodies (occurrence >= {min_occ}%)")
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", nargs=4, type=float, required=True,
                    metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    ap.add_argument("--min-occ", type=int, default=25,
                    help="JRC: min %% of time a pixel must be water")
    ap.add_argument("--out", default="data/raw/structures.csv")
    ap.add_argument("--skip-jrc", action="store_true")
    ap.add_argument("--skip-osm", action="store_true")
    a = ap.parse_args()

    parts = []
    if not a.skip_osm:
        try:
            parts.append(osm_structures(a.bbox))
        except Exception as ex:
            print("OSM step failed:", ex)
    if not a.skip_jrc:
        try:
            parts.append(jrc_waterbodies(a.bbox, a.min_occ))
        except Exception as ex:
            print("JRC step failed:", ex)
    parts = [p for p in parts if not p.empty]
    if not parts:
        raise SystemExit("Nothing fetched - check your internet connection.")
    df = pd.concat(parts, ignore_index=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    print(f"Wrote {a.out}: {len(df)} rows")
    print(df.groupby(["source", "type"]).size().to_string())


if __name__ == "__main__":
    main()
