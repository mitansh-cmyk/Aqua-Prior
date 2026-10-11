#!/usr/bin/env python3
"""
prepare_wells.py - turn the India-WRIS national manual groundwater-level export
into the data/raw/wells.csv that build_features.py expects.

Input : groundwater-level-collected-manually.csv   (national file, ~2.4M rows)
Output: data/raw/wells.csv           one row per well + date  (columns the script needs)
        data/raw/wells_summary.csv   one row per well (coverage, distance to box, usable flag)

Run (Python 3.9+, needs pandas + numpy only):
    python prepare_wells.py --src groundwater-level-collected-manually.csv \
        --bbox 74.06 18.10 74.26 18.30 --years 2009 2023

Then run build_features.py with the SAME bbox:
    python build_features.py --bbox 74.06 18.10 74.26 18.30 --cell 500 --years 2009 2023 \
        --well-radius-km 25

What it does
  1. Reads the national file in chunks (low memory) and keeps only rows inside
     the bbox + a buffer (wells outside the box still influence cells within
     the well radius, so the buffer should be >= --well-radius-km).
  2. Keeps ONLY data_type_code == HGZ (manual depth to water, metres below ground).
     Drops MSL (water level as elevation above sea level - different meaning)
     and GGZ (telemetry).
  3. Parses dates, drops bad/missing values, averages duplicate well+date rows.
  4. Restricts to the --years window so trends use the same period as rainfall.
  5. Writes wells.csv and a per-well summary, and prints a coverage report
     telling you how many wells will survive build_features.py's filter.

Notes
  * level is DEPTH BELOW GROUND (m). A bigger number = deeper water table.
  * The national file ends in 2023-05; there is no 2024 data in it.
  * Readings exist only in Jan, Mar, May, Aug, Oct, Nov. build_features.py uses
    Mar-May (pre-monsoon) and Oct-Dec (post-monsoon), i.e. effectively Mar/May
    and Oct/Nov.
"""
import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

USECOLS = ["station_name", "station_code", "station_type", "agency_name", "well_type",
           "well_aquifer_type", "latitude", "longitude", "well_depth", "date",
           "data_type_code", "data_value"]
PRE_MONTHS = [3, 4, 5]          # keep in sync with build_features.py
POST_MONTHS = [10, 11, 12]
MAX_LEVEL_M = 150.0             # anything deeper is treated as a data-entry error
MIN_LEVEL_M = -5.0              # small negatives (above ground / flowing) are kept


def log(msg):
    print(f"[{pd.Timestamp.now():%H:%M:%S}] {msg}", flush=True)


def km_to_deg(km, lat):
    return km / 111.0, km / (111.0 * math.cos(math.radians(lat)))


def dist_to_box_km(lat, lon, bbox):
    """Distance (km) from points to the bbox edge; 0 if inside."""
    minlon, minlat, maxlon, maxlat = bbox
    midlat = (minlat + maxlat) / 2
    dx = np.maximum.reduce([minlon - lon, np.zeros_like(lon), lon - maxlon]) * 111.0 * math.cos(math.radians(midlat))
    dy = np.maximum.reduce([minlat - lat, np.zeros_like(lat), lat - maxlat]) * 111.0
    return np.hypot(dx, dy)


def read_region(src, bbox, buffer_km):
    minlon, minlat, maxlon, maxlat = bbox
    dlat, dlon = km_to_deg(buffer_km, (minlat + maxlat) / 2)
    lo = (minlon - dlon, minlat - dlat, maxlon + dlon, maxlat + dlat)
    parts, total = [], 0
    for chunk in pd.read_csv(src, usecols=USECOLS, dtype={"station_code": str},
                             chunksize=500_000, low_memory=False):
        total += len(chunk)
        c = chunk[(chunk.data_type_code == "HGZ")
                  & (chunk.station_type == "Ground Water")
                  & chunk.longitude.between(lo[0], lo[2])
                  & chunk.latitude.between(lo[1], lo[3])]
        if len(c):
            parts.append(c)
    log(f"Read {total:,} rows from {Path(src).name}")
    if not parts:
        raise SystemExit("No HGZ rows inside the bbox + buffer - check --bbox (lon lat order!)")
    return pd.concat(parts, ignore_index=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="national groundwater-level csv")
    ap.add_argument("--bbox", nargs=4, type=float, required=True,
                    metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    ap.add_argument("--years", nargs=2, type=int, default=[2009, 2023],
                    help="keep readings from these years (inclusive)")
    ap.add_argument("--buffer-km", type=float, default=30,
                    help="keep wells this far outside the bbox (>= well radius)")
    ap.add_argument("--well-radius-km", type=float, default=25,
                    help="radius used only for the coverage report")
    ap.add_argument("--min-pre-years", type=int, default=6,
                    help="min pre-monsoon years per well (match WELLS_MIN_YEARS)")
    ap.add_argument("--out", default="data/raw/wells.csv")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    y0, y1 = args.years

    df = read_region(args.src, args.bbox, args.buffer_km)
    log(f"Rows in bbox+{args.buffer_km:g} km buffer (HGZ only): {len(df):,}  "
        f"({df.station_code.nunique()} wells)")

    # ---- clean --------------------------------------------------------------
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["level"] = pd.to_numeric(df["data_value"], errors="coerce")
    n0 = len(df)
    df = df.dropna(subset=["date", "level", "latitude", "longitude", "station_code"])
    bad = (df.level > MAX_LEVEL_M) | (df.level < MIN_LEVEL_M)
    log(f"Dropped {n0 - len(df)} rows with missing values and {int(bad.sum())} implausible levels")
    df = df[~bad]
    df = df[(df.date.dt.year >= y0) & (df.date.dt.year <= y1)]
    log(f"Rows in {y0}-{y1}: {len(df):,}")

    # one coordinate/metadata record per well
    meta = (df.sort_values("date").groupby("station_code")
              .agg(station_name=("station_name", "first"), agency_name=("agency_name", "first"),
                   lat=("latitude", "first"), lon=("longitude", "first"),
                   well_type=("well_type", "first"), aquifer_type=("well_aquifer_type", "first"),
                   well_depth_m=("well_depth", "first")))
    # average duplicate well+date readings
    ts = (df.groupby(["station_code", "date"], as_index=False)["level"].mean())
    n_dup = len(df) - len(ts)
    if n_dup:
        log(f"Averaged {n_dup} duplicate well+date rows")
    ts = ts.merge(meta, left_on="station_code", right_index=True)
    ts = ts.rename(columns={"station_code": "well_id"})
    ts["date"] = ts["date"].dt.strftime("%Y-%m-%d")           # ISO, as build_features expects
    cols = ["well_id", "station_name", "agency_name", "lat", "lon", "date", "level",
            "well_type", "aquifer_type", "well_depth_m"]
    ts = ts[cols].sort_values(["well_id", "date"])
    ts.to_csv(out, index=False)
    log(f"Wrote {out}  ({len(ts):,} rows, {ts.well_id.nunique()} wells)")

    # ---- per-well summary + coverage report ----------------------------------
    d = pd.to_datetime(ts["date"])
    ts["year"], ts["month"] = d.dt.year, d.dt.month
    pre = ts[ts.month.isin(PRE_MONTHS)].groupby("well_id").year.nunique().rename("pre_years")
    post = ts[ts.month.isin(POST_MONTHS)].groupby("well_id").year.nunique().rename("post_years")
    s = meta.join(pre).join(post).fillna({"pre_years": 0, "post_years": 0})
    s["n_readings"] = ts.groupby("well_id").size()
    s["first_date"] = ts.groupby("well_id").date.min()
    s["last_date"] = ts.groupby("well_id").date.max()
    s["km_to_box"] = dist_to_box_km(s.lat.values, s.lon.values, args.bbox).round(1)
    s["inside_box"] = s.km_to_box == 0
    s["usable"] = s.pre_years >= args.min_pre_years
    s["in_radius"] = s.km_to_box <= args.well_radius_km
    s.sort_values("km_to_box").to_csv(out.with_name("wells_summary.csv"))

    inside = s[s.inside_box & s.usable]
    near = s[s.in_radius & s.usable]
    log("---- COVERAGE REPORT ----")
    log(f"Wells in bbox (any data):            {int(s.inside_box.sum())}")
    log(f"Usable wells INSIDE bbox (>= {args.min_pre_years} pre-monsoon yrs): {len(inside)}")
    log(f"Usable wells within {args.well_radius_km:g} km of bbox:     {len(near)}")
    for r in (10, 15, 25):
        log(f"   within {r:>2} km: {int(((s.km_to_box <= r) & s.usable).sum())}")
    if len(near) < 5:
        log("WARNING: fewer than 5 usable wells - lower --min-pre-years, widen the radius or the years.")
    log("Readings per month (all kept rows): " + str(ts.month.value_counts().sort_index().to_dict()))
    log("Readings per year: " + str(ts.year.value_counts().sort_index().to_dict()))
    print("\nNearest usable wells:")
    print(near.sort_values("km_to_box")[["station_name", "agency_name", "km_to_box",
                                         "pre_years", "post_years", "n_readings"]].head(20).to_string())
    log("Next: python build_features.py --bbox "
        + " ".join(f"{b:g}" for b in args.bbox)
        + f" --cell 500 --years {y0} {y1} --well-radius-km {args.well_radius_km:g}")


if __name__ == "__main__":
    main()
