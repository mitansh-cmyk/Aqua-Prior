#!/usr/bin/env python3
"""
Groundwater Recharge Planner - grid building + feature extraction (corrected)
=============================================================================
Builds ONE metric grid for a study area, then extracts every layer onto it,
producing one table (one row per cell, one column per feature).

Install (Python 3.9+):
    pip install geopandas rasterio rasterstats pysheds scipy requests pandas numpy shapely pyogrio boto3

Run (example: 20x20 km box, 500 m cells):
    python build_features.py --bbox 76.80 28.40 77.00 28.60 --cell 500 --years 2014 2024

Folder layout (created automatically):
    data/raw/    <- files YOU download manually (wells.csv, geology.gpkg, ...)
    data/work/   <- cached downloads and intermediate rasters
    outputs/     <- grid_features.gpkg / .csv

Steps that need manual input files are skipped (with a warning) if the file is
missing, so you can run the script repeatedly as you collect data.
ALWAYS rerun with all steps (default): outputs are rewritten from scratch each
run, and cached downloads in data/work/ make reruns fast.

Auto-downloaded (no login): DEM, land cover, rainfall, soil.
Manual input files:
    data/raw/wells.csv          India-WRIS well levels
    data/raw/geology.gpkg       Bhuvan / GSI geology (polygons)
    data/raw/structures.*       Geo-MGNREGA / water-body points or polygons
    data/raw/blocks.gpkg        block boundaries (+ optional extraction_stage.csv)
"""
import argparse
import gzip
import math
import shutil
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
import requests
from rasterio.merge import merge
from rasterio.transform import rowcol
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterio.windows import Window, from_bounds
from rasterstats import zonal_stats
from scipy.spatial import cKDTree
from shapely.geometry import box

warnings.filterwarnings("ignore", category=RuntimeWarning)
if not hasattr(np, "in1d"):          # pysheds still calls np.in1d, removed in NumPy 2
    np.in1d = np.isin

RAW = Path("data/raw")
WORK = Path("data/work")
OUT = Path("outputs")

# ----------------------------------------------------------------------------
# EDIT THESE to match the column names in YOUR downloaded files
# ----------------------------------------------------------------------------
WELLS_COLS = dict(well_id="well_id", lat="lat", lon="lon", date="date", level="level")
WELLS_PRE_MONTHS = [3, 4, 5]        # pre-monsoon
WELLS_POST_MONTHS = [10, 11, 12]    # post-monsoon
WELLS_MIN_YEARS = 6                 # min years of pre-monsoon data per well
GEOLOGY_FILE = RAW / "geology.gpkg"
GEOLOGY_COL = "lithology"           # attribute holding rock / aquifer type
STRUCTURES_GLOB = "structures.*"    # structures.csv / .gpkg / .shp / .geojson
STRUCTURES_TYPE_COL = "type"        # optional: check dam / pond / etc.
BLOCKS_FILE = RAW / "blocks.gpkg"
BLOCKS_NAME_COL = "block"
BLOCKS_STAGE_CSV = RAW / "extraction_stage.csv"   # columns: block, stage_pct, category

WORLDCOVER_CLASSES = {
    10: "tree", 20: "shrub", 30: "grass", 40: "crop", 50: "built",
    60: "bare", 70: "snow", 80: "water", 90: "wetland", 95: "mangrove", 100: "moss",
}


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def log(msg):
    print(f"[{pd.Timestamp.now():%H:%M:%S}] {msg}", flush=True)


def download(url, dest):
    dest = Path(dest)
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    tmp.rename(dest)
    return dest


def read_window(src, bounds):
    """Read band 1 of `src` over lon/lat bounds -> (float array with NaN nodata, transform)."""
    win = from_bounds(*bounds, transform=src.transform)
    win = Window(math.floor(win.col_off), math.floor(win.row_off),
                 math.ceil(win.width) + 2, math.ceil(win.height) + 2)
    nd = src.nodata
    arr = src.read(1, window=win, boundless=True,
                   fill_value=nd if nd is not None else 0).astype("float64")
    if nd is not None:
        arr[arr == nd] = np.nan
    return arr, src.window_transform(win)


def sample_array(arr, transform, lons, lats):
    rows, cols = rowcol(transform, lons, lats)
    rows, cols = np.asarray(rows), np.asarray(cols)
    ok = (rows >= 0) & (rows < arr.shape[0]) & (cols >= 0) & (cols < arr.shape[1])
    out = np.full(len(lons), np.nan)
    out[ok] = arr[rows[ok], cols[ok]]
    return out


def mosaic_remote(urls, bounds, out_path):
    """Mosaic remote COG tiles (read only the bbox) into a local GeoTIFF."""
    out_path = Path(out_path)
    if out_path.exists():
        return out_path
    srcs = []
    for u in urls:
        try:
            srcs.append(rasterio.open(u))
        except Exception as e:  # tile missing (e.g. ocean)
            log(f"  tile skipped: {u.split('/')[-1]} ({type(e).__name__})")
    if not srcs:
        raise RuntimeError("No tiles could be opened - check network / bbox")
    arr, tr = merge(srcs, bounds=bounds)
    profile = dict(driver="GTiff", height=arr.shape[1], width=arr.shape[2],
                   count=arr.shape[0], dtype=arr.dtype, crs=srcs[0].crs,
                   transform=tr, nodata=srcs[0].nodata, compress="deflate")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(arr)
    for s in srcs:
        s.close()
    return out_path


def reproject_raster(src_path, dst_path, dst_crs, res, resampling):
    dst_path = Path(dst_path)
    if dst_path.exists():
        return dst_path
    with rasterio.open(src_path) as src:
        tr, w, h = calculate_default_transform(src.crs, dst_crs, src.width, src.height,
                                               *src.bounds, resolution=res)
        profile = src.profile.copy()
        profile.update(crs=dst_crs, transform=tr, width=w, height=h, compress="deflate")
        with rasterio.open(dst_path, "w", **profile) as dst:
            reproject(rasterio.band(src, 1), rasterio.band(dst, 1),
                      src_transform=src.transform, src_crs=src.crs,
                      dst_transform=tr, dst_crs=dst_crs, resampling=resampling,
                      src_nodata=src.nodata, dst_nodata=src.nodata)
    return dst_path


def tiles_1deg(bounds):
    minx, miny, maxx, maxy = bounds
    for lat in range(math.floor(miny), math.floor(maxy) + 1):
        for lon in range(math.floor(minx), math.floor(maxx) + 1):
            yield lat, lon


def tiles_3deg(bounds):
    minx, miny, maxx, maxy = bounds
    for lat in range(int(math.floor(miny / 3) * 3), int(math.floor(maxy / 3) * 3) + 1, 3):
        for lon in range(int(math.floor(minx / 3) * 3), int(math.floor(maxx / 3) * 3) + 1, 3):
            yield lat, lon


def hemi(lat, lon):
    return ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")


def load_points(path, lat="lat", lon="lon"):
    path = Path(path)
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
        return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[lon], df[lat]), crs=4326)
    return gpd.read_file(path)


# ----------------------------------------------------------------------------
# STEP 0: GRID
# ----------------------------------------------------------------------------
def build_grid(bbox, cell):
    area = gpd.GeoSeries([box(*bbox)], crs=4326)
    crs = area.estimate_utm_crs()
    minx, miny, maxx, maxy = area.to_crs(crs).total_bounds
    x0, y0 = math.floor(minx / cell) * cell, math.floor(miny / cell) * cell
    xs = np.arange(x0, maxx, cell)
    ys = np.arange(y0, maxy, cell)
    geoms, ids = [], []
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            geoms.append(box(x, y, x + cell, y + cell))
            ids.append(f"r{j:03d}c{i:03d}")
    grid = gpd.GeoDataFrame({"cell_id": ids}, geometry=geoms, crs=crs)
    cen = grid.geometry.centroid
    ll = cen.to_crs(4326)
    grid["cx"], grid["cy"] = cen.x.values, cen.y.values
    grid["lon"], grid["lat"] = ll.x.values, ll.y.values
    log(f"Grid: {len(grid)} cells of {cell} m, CRS {crs.to_string()}")
    return grid


def padded_bounds(grid, pad=0.03):
    ll = grid.to_crs(4326).total_bounds
    return (ll[0] - pad, ll[1] - pad, ll[2] + pad, ll[3] + pad)


# ----------------------------------------------------------------------------
# STEP 1: DEM -> terrain & drainage   (Copernicus GLO-30 on AWS, anonymous)
# ----------------------------------------------------------------------------
def terrain_rasters(dem_utm, outdir, stream_area_ha=50):
    from pysheds.grid import Grid

    outdir = Path(outdir)
    with rasterio.open(dem_utm) as src:
        prof = src.profile.copy()
        res = abs(src.transform.a)
        dem_arr = src.read(1).astype("float64")
        if src.nodata is not None:
            dem_arr[dem_arr == src.nodata] = np.nan
    fill_val = np.nanmin(dem_arr)
    dem_arr = np.where(np.isnan(dem_arr), fill_val, dem_arr)

    grid = Grid.from_raster(str(dem_utm))
    dem = grid.read_raster(str(dem_utm))
    pit = grid.fill_pits(dem)
    flooded = grid.fill_depressions(pit)
    inflated = grid.resolve_flats(flooded)
    fdir = grid.flowdir(inflated)
    acc = np.asarray(grid.accumulation(fdir)).astype("float64")
    depress = np.asarray(flooded).astype("float64") - dem_arr

    dzdy, dzdx = np.gradient(dem_arr, res)
    slope_rad = np.arctan(np.hypot(dzdx, dzdy))
    slope_deg = np.degrees(slope_rad)
    tanb = np.tan(np.clip(slope_rad, 0.001, None))
    twi = np.log(((acc + 1) * res) / tanb)

    thresh = (stream_area_ha * 10_000) / (res * res)
    stream = (acc >= thresh).astype("float32")

    prof.update(dtype="float32", nodata=-9999.0, compress="deflate")
    paths = {}
    for name, a in dict(elev=dem_arr, slope=slope_deg, flowacc=acc, twi=twi,
                        depress=depress, stream=stream).items():
        p = outdir / f"terrain_{name}.tif"
        with rasterio.open(p, "w", **prof) as dst:
            dst.write(a.astype("float32"), 1)
        paths[name] = p
    return paths, res


def step_dem(grid, bounds, args):
    log("DEM: downloading Copernicus GLO-30 tiles from AWS ...")
    urls = []
    for lat, lon in tiles_1deg(bounds):
        ns, ew = hemi(lat, lon)
        name = f"Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM"
        urls.append(f"https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif")
    ll = mosaic_remote(urls, bounds, WORK / "dem_4326.tif")
    utm = reproject_raster(ll, WORK / "dem_utm.tif", grid.crs, 30, Resampling.bilinear)
    log("DEM: deriving slope, flow accumulation, TWI, depressions, streams ...")
    paths, res = terrain_rasters(utm, WORK, stream_area_ha=args.stream_ha)

    def zs(name, stat):
        z = zonal_stats(grid, str(paths[name]), stats=[stat], nodata=-9999.0)
        return np.array([d[stat] for d in z], dtype=float)   # None -> NaN

    grid["elev_mean_m"] = zs("elev", "mean")
    grid["elev_relief_m"] = zs("elev", "max") - zs("elev", "min")
    grid["slope_mean_deg"] = zs("slope", "mean")
    grid["twi_mean"] = zs("twi", "mean")
    grid["flowacc_max_ha"] = zs("flowacc", "max") * res * res / 10_000
    grid["depression_max_m"] = zs("depress", "max")
    frac = zs("stream", "mean")
    grid["drainage_density_km_km2"] = frac / (res / 1000.0)   # stream length per area
    return grid


# ----------------------------------------------------------------------------
# STEP 2: LAND COVER (ESA WorldCover 2021, AWS)
# ----------------------------------------------------------------------------
def step_landcover(grid, bounds, args):
    log("Land cover: downloading ESA WorldCover tiles from AWS ...")
    urls = []
    for lat, lon in tiles_3deg(bounds):
        ns, ew = hemi(lat, lon)
        urls.append("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                    f"ESA_WorldCover_10m_2021_v200_{ns}{abs(lat):02d}{ew}{abs(lon):03d}_Map.tif")
    ll = mosaic_remote(urls, bounds, WORK / "lc_4326.tif")
    utm = reproject_raster(ll, WORK / "lc_utm.tif", grid.crs, 10, Resampling.nearest)
    log("Land cover: computing class fractions per cell ...")
    z = zonal_stats(grid, str(utm), categorical=True)
    for code, name in WORLDCOVER_CLASSES.items():
        grid[f"lc_{name}_frac"] = [
            (d.get(code, 0) / max(sum(d.values()), 1)) if d else np.nan for d in z]
    grid["lc_dominant"] = [
        WORLDCOVER_CLASSES.get(max(d, key=d.get)) if d else None for d in z]
    return grid


# ----------------------------------------------------------------------------
# STEP 3: RAINFALL (CHIRPS v2 monthly, ~5 km, CHC server)
# ----------------------------------------------------------------------------
def step_rain(grid, bounds, args):
    y0, y1 = args.years
    cache = WORK / f"rain_{y0}_{y1}.npz"
    lons, lats = grid["lon"].values, grid["lat"].values
    if cache.exists():
        d = np.load(cache)
        annual, monsoon = d["annual"], d["monsoon"]
    else:
        log("Rainfall: downloading CHIRPS monthly files (this takes a while) ...")
        annual = np.full((y1 - y0 + 1, len(grid)), np.nan)
        monsoon = np.full_like(annual, np.nan)
        failures = 0
        for yi, y in enumerate(range(y0, y1 + 1)):
            months = []
            for m in range(1, 13):
                url = ("https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/tifs/"
                       f"chirps-v2.0.{y}.{m:02d}.tif.gz")
                gz = WORK / "chirps" / f"{y}.{m:02d}.tif.gz"
                tif = gz.with_suffix("")
                try:
                    download(url, gz)
                    with gzip.open(gz, "rb") as fi, open(tif, "wb") as fo:
                        shutil.copyfileobj(fi, fo)
                    with rasterio.open(tif) as src:
                        arr, tr = read_window(src, bounds)
                    arr[arr < 0] = np.nan
                    months.append(sample_array(arr, tr, lons, lats))
                except Exception as e:
                    failures += 1
                    log(f"  CHIRPS {y}-{m:02d} failed: {type(e).__name__} {e}")
                    months.append(np.full(len(grid), np.nan))
                finally:
                    tif.unlink(missing_ok=True)
                    gz.unlink(missing_ok=True)
            mm = np.vstack(months)
            # a year with ANY missing month is NaN (never silently counted as 0 mm)
            annual[yi] = np.where(np.isnan(mm).any(axis=0), np.nan, mm.sum(axis=0))
            monsoon[yi] = np.where(np.isnan(mm[5:9]).any(axis=0), np.nan, mm[5:9].sum(axis=0))
            log(f"  {y} done")
        if failures == 0:
            np.savez(cache, annual=annual, monsoon=monsoon)
        else:
            log(f"  {failures} CHIRPS files failed - result NOT cached, rerun to retry")

    yrs = np.arange(y0, y1 + 1)
    grid["rain_annual_mm"] = np.nanmean(annual, axis=0)
    grid["rain_monsoon_mm"] = np.nanmean(monsoon, axis=0)
    grid["rain_monsoon_share"] = grid["rain_monsoon_mm"] / grid["rain_annual_mm"]
    grid["rain_cv"] = np.nanstd(annual, axis=0) / np.nanmean(annual, axis=0)
    # NaN-aware least-squares slope (mm per year)
    ok = ~np.isnan(annual)
    x = yrs[:, None].astype(float)
    n = ok.sum(axis=0)
    xm = (x * ok).sum(axis=0) / n
    ym = np.nansum(annual, axis=0) / n
    grid["rain_trend_mm_yr"] = (np.nansum((x - xm) * (annual - ym), axis=0)
                                / (((x - xm) ** 2) * ok).sum(axis=0))
    return grid


# ----------------------------------------------------------------------------
# STEP 4: SOIL (SoilGrids 250 m, ISRIC)
# ----------------------------------------------------------------------------
def hsg_from_texture(sand, clay):
    """Rough hydrologic soil group from texture (heuristic - validate locally)."""
    if np.isnan(sand) or np.isnan(clay):
        return None
    if sand >= 70 and clay < 10:
        return "A"
    if sand >= 50 and clay < 20:
        return "B"
    if clay < 35:
        return "C"
    return "D"


def step_soil(grid, bounds, args):
    log("Soil: reading SoilGrids (sand, clay, silt) ...")
    lons, lats = grid["lon"].values, grid["lat"].values
    base = "https://files.isric.org/soilgrids/latest/data"
    for prop in ["sand", "clay", "silt"]:
        layers = []
        for depth in ["5-15cm", "15-30cm"]:
            url = f"/vsicurl/{base}/{prop}/{prop}_{depth}_mean.vrt"
            with rasterio.open(url) as src, \
                    WarpedVRT(src, crs="EPSG:4326", resampling=Resampling.nearest) as vrt:
                arr, tr = read_window(vrt, bounds)
            layers.append(sample_array(arr, tr, lons, lats) / 10.0)  # g/kg -> %
        grid[f"soil_{prop}_pct"] = np.nanmean(layers, axis=0)
    grid["soil_hsg"] = [hsg_from_texture(s, c) for s, c in
                        zip(grid["soil_sand_pct"], grid["soil_clay_pct"])]
    grid["soil_infil_score"] = grid["soil_hsg"].map(
        {"A": 1.0, "B": 0.75, "C": 0.4, "D": 0.15})
    return grid


# ----------------------------------------------------------------------------
# STEP 5: WELLS (India-WRIS CSV) -> pre/post-monsoon, trend, IDW surface
# ----------------------------------------------------------------------------
def step_wells(grid, args):
    path = RAW / "wells.csv"
    if not path.exists():
        log("Wells: data/raw/wells.csv not found - SKIPPED")
        return grid
    c = WELLS_COLS
    df = pd.read_csv(path).rename(columns={v: k for k, v in c.items()})
    d = pd.to_datetime(df["date"], errors="coerce", format="%Y-%m-%d")   # ISO dates first
    if d.isna().mean() > 0.5:                                           # else dd-mm-yyyy style
        d = pd.to_datetime(df["date"], errors="coerce", dayfirst=True)
    df["date"] = d
    df["level"] = pd.to_numeric(df["level"], errors="coerce")
    df = df.dropna(subset=["date", "lat", "lon", "level", "well_id"])
    df["year"], df["month"] = df["date"].dt.year, df["date"].dt.month
    pre = df[df["month"].isin(WELLS_PRE_MONTHS)].groupby(["well_id", "year"])["level"].mean().rename("pre")
    post = df[df["month"].isin(WELLS_POST_MONTHS)].groupby(["well_id", "year"])["level"].mean().rename("post")
    ann = pd.concat([pre, post], axis=1).reset_index()
    loc = df.groupby("well_id")[["lat", "lon"]].first()

    rows = []
    for wid, g in ann.groupby("well_id"):
        gp = g.dropna(subset=["pre"]).sort_values("year")
        if len(gp) < WELLS_MIN_YEARS or wid not in loc.index:
            continue
        rows.append(dict(
            well_id=wid, lat=loc.loc[wid, "lat"], lon=loc.loc[wid, "lon"],
            # level = depth below ground (m). Positive slope = water table FALLING.
            decline_m_yr=np.polyfit(gp.year, gp.pre, 1)[0],
            depth_recent_m=gp.pre.tail(3).mean(),
            fluct_m=(g.pre - g.post).mean(),   # >0: water table rises after monsoon
            n_years=len(gp)))
    w = pd.DataFrame(rows)
    n_all = df["well_id"].nunique()
    log(f"Wells: {len(w)} wells pass the >= {WELLS_MIN_YEARS}-year filter (of {n_all} in file)")
    if len(w) < 5:
        log("  WARNING: fewer than 5 usable wells - interpolation not defensible")
    if w.empty:
        return grid
    wg = gpd.GeoDataFrame(w, geometry=gpd.points_from_xy(w.lon, w.lat), crs=4326).to_crs(grid.crs)
    wxy = np.c_[wg.geometry.x, wg.geometry.y]
    cxy = grid[["cx", "cy"]].values
    tree = cKDTree(wxy)
    k = min(6, len(w))
    dist, idx = tree.query(cxy, k=k)
    dist, idx = np.atleast_2d(dist.T).T, np.atleast_2d(idx.T).T
    wts = 1.0 / np.maximum(dist, 1.0) ** 2
    wts[dist > args.well_radius_km * 1000] = 0
    for col, new in [("decline_m_yr", "gw_decline_m_yr"), ("depth_recent_m", "gw_depth_m"),
                     ("fluct_m", "gw_fluct_m")]:
        vals = w[col].values[idx]
        s = wts.sum(axis=1)
        grid[new] = np.where(s > 0, (wts * vals).sum(axis=1) / np.where(s > 0, s, 1), np.nan)
    grid["gw_nearest_well_km"] = dist[:, 0] / 1000
    grid["gw_wells_within_10km"] = tree.query_ball_point(cxy, r=10_000, return_length=True)
    grid["gw_confidence"] = np.clip(1 - grid["gw_nearest_well_km"] / args.well_radius_km, 0, 1)
    return grid


# ----------------------------------------------------------------------------
# STEP 6: EXISTING STRUCTURES
# ----------------------------------------------------------------------------
def step_structures(grid, args):
    files = list(RAW.glob(STRUCTURES_GLOB))
    if not files:
        log("Structures: data/raw/structures.* not found - SKIPPED")
        return grid
    gdf = load_points(files[0]).to_crs(grid.crs)
    gdf["geometry"] = gdf.geometry.representative_point()
    log(f"Structures: {len(gdf)} features from {files[0].name}")
    j = gpd.sjoin(gdf, grid[["cell_id", "geometry"]], predicate="within")
    grid["struct_count"] = grid.cell_id.map(j.groupby("cell_id").size()).fillna(0).astype(int)
    if STRUCTURES_TYPE_COL in gdf.columns:
        t = j.groupby(["cell_id", STRUCTURES_TYPE_COL]).size().unstack(fill_value=0)
        t.columns = [f"struct_{str(c).lower().replace(' ', '_')}" for c in t.columns]
        grid = grid.merge(t, left_on="cell_id", right_index=True, how="left")
        for c in t.columns:
            grid[c] = grid[c].fillna(0).astype(int)
    d, _ = cKDTree(np.c_[gdf.geometry.x, gdf.geometry.y]).query(grid[["cx", "cy"]].values)
    grid["struct_nearest_m"] = d
    return grid


# ----------------------------------------------------------------------------
# STEP 7: GEOLOGY (dominant class by area)
# ----------------------------------------------------------------------------
def step_geology(grid, args):
    if not GEOLOGY_FILE.exists():
        log(f"Geology: {GEOLOGY_FILE} not found - SKIPPED")
        return grid
    geo = gpd.read_file(GEOLOGY_FILE).to_crs(grid.crs)[[GEOLOGY_COL, "geometry"]]
    inter = gpd.overlay(grid[["cell_id", "geometry"]], geo, how="intersection")
    inter["a"] = inter.geometry.area
    dom = inter.sort_values("a", ascending=False).drop_duplicates("cell_id").set_index("cell_id")
    grid["geology"] = grid.cell_id.map(dom[GEOLOGY_COL])
    return grid


# ----------------------------------------------------------------------------
# STEP 8: BLOCKS + CGWB extraction stage
# ----------------------------------------------------------------------------
def step_blocks(grid, args):
    if not BLOCKS_FILE.exists():
        log(f"Blocks: {BLOCKS_FILE} not found - SKIPPED")
        return grid
    blk = gpd.read_file(BLOCKS_FILE).to_crs(grid.crs)
    if BLOCKS_STAGE_CSV.exists():
        st = pd.read_csv(BLOCKS_STAGE_CSV)
        blk = blk.merge(st, left_on=BLOCKS_NAME_COL, right_on="block", how="left",
                        suffixes=("", "_csv"))
    pts = gpd.GeoDataFrame(grid[["cell_id"]], geometry=gpd.points_from_xy(grid["cx"], grid["cy"]),
                           crs=grid.crs)
    j = gpd.sjoin(pts, blk, how="left", predicate="within")
    j = j.drop_duplicates("cell_id").set_index("cell_id")
    grid["block"] = grid.cell_id.map(j[BLOCKS_NAME_COL])
    for c in ["stage_pct", "category"]:
        if c in j.columns:
            grid[f"gw_{c}"] = grid.cell_id.map(j[c])
    return grid


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
STEPS = ["dem", "landcover", "rain", "soil", "wells", "structures", "geology", "blocks"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", nargs=4, type=float, required=True,
                    metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    ap.add_argument("--cell", type=float, default=500, help="cell size in metres")
    ap.add_argument("--years", nargs=2, type=int, default=[2014, 2024])
    ap.add_argument("--steps", nargs="+", default=STEPS, choices=STEPS)
    ap.add_argument("--stream-ha", type=float, default=50,
                    help="contributing area (ha) above which a cell is a stream")
    ap.add_argument("--well-radius-km", type=float, default=15,
                    help="max distance a well can influence a cell")
    ap.add_argument("--s3", default=None, help="optional s3://bucket/prefix/ upload of outputs")
    args = ap.parse_args()

    for d in (RAW, WORK, OUT):
        d.mkdir(parents=True, exist_ok=True)

    grid = build_grid(args.bbox, args.cell)
    bounds = padded_bounds(grid)
    grid.to_file(OUT / "grid_only.gpkg", driver="GPKG")

    runners = dict(
        dem=lambda g: step_dem(g, bounds, args),
        landcover=lambda g: step_landcover(g, bounds, args),
        rain=lambda g: step_rain(g, bounds, args),
        soil=lambda g: step_soil(g, bounds, args),
        wells=lambda g: step_wells(g, args),
        structures=lambda g: step_structures(g, args),
        geology=lambda g: step_geology(g, args),
        blocks=lambda g: step_blocks(g, args),
    )
    for s in STEPS:
        if s in args.steps:
            try:
                grid = runners[s](grid)
            except Exception as e:
                log(f"STEP '{s}' FAILED: {type(e).__name__}: {e}  (continuing)")

    grid.to_file(OUT / "grid_features.gpkg", driver="GPKG")
    grid.drop(columns="geometry").to_csv(OUT / "grid_features.csv", index=False)
    log(f"Wrote {OUT / 'grid_features.gpkg'} and .csv  ({len(grid)} rows x {grid.shape[1]} cols)")
    log("Null share per column (high = check that layer):")
    print(grid.drop(columns="geometry").isna().mean().round(2).to_string())

    if args.s3:
        import boto3
        bucket, _, prefix = args.s3.replace("s3://", "").partition("/")
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        s3 = boto3.client("s3")
        for f in ["grid_features.gpkg", "grid_features.csv", "grid_only.gpkg"]:
            s3.upload_file(str(OUT / f), bucket, f"{prefix}{f}")
        log(f"Uploaded to s3://{bucket}/{prefix}")


if __name__ == "__main__":
    main()
