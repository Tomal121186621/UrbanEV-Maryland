#!/usr/bin/env python3
"""
validate_vs_chargepoint.py — diurnal-occupancy validation of a MATSim run
against ChargePoint MD observed snapshots.

Pipeline:
  1.  Build sim_station -> CP station_id crosswalk by coordinate-based join:
        sim charger (x, y in EPSG:26985)
        -> nearest AFDC station (Latitude/Longitude -> reprojected)
        -> CP station_id via afdc_cp_crosswalk_v2.
  2.  Aggregate sim per-charger occupancy (xy.gz) to per-station 24-hour
      utilization profile.
  3.  Aggregate CP charging_session_v2 snapshots to per-station 24-hour
      utilization profile.
  4.  Per-matched-station metrics: Pearson r, RMSE, peak-hour absolute error.
  5.  Plots: system-wide diurnal overlay, peak-hour utilization scatter.

Run:
    py analysis/validate_vs_chargepoint.py
    py analysis/validate_vs_chargepoint.py --run output/prod_100pct --iter 36
    py analysis/validate_vs_chargepoint.py --match-tolerance-m 150
"""
from __future__ import annotations
import argparse
import csv
import gzip
import sqlite3
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pyproj import Transformer
from scipy.spatial import cKDTree

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = REPO_ROOT.parent
DATA_DIR = PROJECT_ROOT / "Baseline Validation" / "Data" / "ChargePoint Data Collection"
CHARGERS_XML = PROJECT_ROOT / "Input" / "chargers" / "chargers.xml"
AFDC_CSV = DATA_DIR / "alt_fuel_stations (Jan 19 2026).csv"
CP_DB = DATA_DIR / "chargepoint_md.db"

# Per project_crs_mislabel memory: chargers.xml + network are EPSG:26985
# (MD State Plane m), despite config claiming 26918.
SIM_CRS = "EPSG:26985"
LATLON_CRS = "EPSG:4326"


def read_sim_chargers(path: Path) -> pd.DataFrame:
    """Parse chargers.xml into a DataFrame with id, type, x, y, plug_count."""
    root = ET.parse(path).getroot()
    rows = []
    for c in root.findall("charger"):
        rows.append({
            "sim_id":     c.get("id"),
            "ctype":      c.get("type"),
            "x":          float(c.get("x")),
            "y":          float(c.get("y")),
            "plug_count": int(c.get("plug_count") or 1),
        })
    df = pd.DataFrame(rows)
    print(f"  sim chargers: {len(df):,}  (L1={(df.ctype=='L1').sum()},"
          f" L2={(df.ctype=='L2').sum()}, DCFC={(df.ctype=='DCFC').sum()},"
          f" DCFC_TESLA={(df.ctype=='DCFC_TESLA').sum()})")
    return df


def aggregate_sim_to_stations(chargers: pd.DataFrame) -> pd.DataFrame:
    """Group chargers at same (x, y) into a logical sim_station. A station can
    aggregate multiple charger entities (e.g., one L1 plug + one L2 plug at the
    same physical site)."""
    g = chargers.groupby(["x", "y"], as_index=False).agg(
        plug_count_total=("plug_count", "sum"),
        sim_ids=("sim_id", list),
        types=("ctype", lambda s: sorted(set(s))),
    )
    g["sim_station_idx"] = range(len(g))
    print(f"  sim stations (unique x,y): {len(g):,}")
    return g


def read_afdc_md(path: Path) -> pd.DataFrame:
    """Filter AFDC catalog to MD electric stations with a present lat/lon."""
    rows = []
    with path.open(encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            if row.get("State") != "MD":
                continue
            if row.get("Fuel Type Code") != "ELEC":
                continue
            lat = row.get("Latitude")
            lon = row.get("Longitude")
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except (TypeError, ValueError):
                continue
            rows.append({
                "afdc_id":  row.get("ID"),
                "lat":      lat_f,
                "lon":      lon_f,
                "ev_l2":    row.get("EV Level2 EVSE Num") or "",
                "ev_dcfc":  row.get("EV DC Fast Count") or "",
                "name":     row.get("Station Name"),
            })
    df = pd.DataFrame(rows)
    print(f"  AFDC MD-ELEC stations w/ lat/lon: {len(df):,}")
    return df


def read_crosswalk(db: Path) -> pd.DataFrame:
    con = sqlite3.connect(db)
    df = pd.read_sql_query(
        "SELECT afdc_station_id, station_id AS cp_station_id, "
        "       match_distance_m, match_method "
        "FROM afdc_cp_crosswalk_v2", con)
    con.close()
    print(f"  AFDC->CP crosswalk rows: {len(df):,}  "
          f"distinct CP stations: {df.cp_station_id.nunique():,}")
    return df


def project_afdc_to_sim_crs(afdc: pd.DataFrame) -> pd.DataFrame:
    t = Transformer.from_crs(LATLON_CRS, SIM_CRS, always_xy=True)
    x, y = t.transform(afdc["lon"].values, afdc["lat"].values)
    afdc = afdc.copy()
    afdc["x_proj"] = x
    afdc["y_proj"] = y
    return afdc


def join_sim_to_afdc(sim_stations: pd.DataFrame, afdc_proj: pd.DataFrame,
                     tol_m: float) -> pd.DataFrame:
    """Nearest-AFDC join per sim station, within tol_m radius."""
    tree = cKDTree(np.c_[afdc_proj["x_proj"], afdc_proj["y_proj"]])
    dist, idx = tree.query(np.c_[sim_stations["x"], sim_stations["y"]], k=1)
    sim_stations = sim_stations.copy()
    sim_stations["afdc_idx"] = idx
    sim_stations["afdc_match_dist_m"] = dist
    sim_stations["afdc_id"] = afdc_proj["afdc_id"].values[idx]
    matched = sim_stations[sim_stations["afdc_match_dist_m"] <= tol_m].copy()
    print(f"  sim<->AFDC within {tol_m:.0f}m: {len(matched):,} / "
          f"{len(sim_stations):,}  "
          f"(median dist={matched['afdc_match_dist_m'].median():.1f}m)")
    return matched


def read_sim_occupancy(xy_gz: Path) -> pd.DataFrame:
    """Read MATSim .xy.gz to DataFrame: time(s), id, x, y, plugs, plugged."""
    with gzip.open(xy_gz, "rt") as f:
        df = pd.read_csv(f, sep="\t")
    # Convert time to hour-of-day (0..23). The file has time as seconds-since-midnight.
    df["hour"] = (df["time"] // 3600) % 24
    df["hour"] = df["hour"].astype(int)
    print(f"  sim occupancy snapshots: {len(df):,}  "
          f"chargers={df['id'].nunique():,}  hours covered={df['hour'].nunique()}")
    return df


def sim_diurnal_by_cp(occ: pd.DataFrame, sim_id_to_cp: dict) -> pd.DataFrame:
    """Return DataFrame indexed by cp_station_id, columns hour 0..23, values =
    aggregate utilization fraction at that CP facility (summed across all sim
    chargers that map to that cp_id).

    Critical: aggregation is at CP-facility level, not sim-station level.
    Multiple sim stations (different AFDC IDs) can map to one CP station_id
    (facility-level reporting in the CP feed). Comparing at the same level on
    both sides removes the level-mismatch / double-counting bias."""
    occ = occ.copy()
    occ["cp_id"] = occ["id"].map(sim_id_to_cp)
    occ = occ.dropna(subset=["cp_id"])
    occ["cp_id"] = occ["cp_id"].astype(int)
    # Sum plugged + plugs across all sim chargers (and stations) sharing a CP id
    # at each snapshot time, then average across snapshots in each hour.
    by_cp_t = occ.groupby(["cp_id", "time"]).agg(
        plugged=("plugged", "sum"),
        plugs=("plugs", "sum")).reset_index()
    by_cp_t["util"] = np.where(by_cp_t["plugs"] > 0,
                               by_cp_t["plugged"] / by_cp_t["plugs"], 0.0)
    by_cp_t["hour"] = (by_cp_t["time"] // 3600).astype(int) % 24
    diurnal = (by_cp_t.groupby(["cp_id", "hour"])["util"]
               .mean().unstack(fill_value=0.0))
    diurnal = diurnal.reindex(columns=range(24), fill_value=0.0)
    return diurnal


def cp_diurnal(db: Path, cp_station_ids: set) -> pd.DataFrame:
    """Return DataFrame indexed by cp_station_id, columns hour 0..23, value =
    utilization fraction averaged over all observed snapshots in that hour."""
    if not cp_station_ids:
        return pd.DataFrame()
    con = sqlite3.connect(db)
    q = (f"SELECT station_id, accessed_time_utc, in_use_ports, available_ports "
         f"FROM charging_session_v2 "
         f"WHERE station_id IN ({','.join('?'*len(cp_station_ids))})")
    df = pd.read_sql_query(q, con, params=list(cp_station_ids))
    con.close()
    df["dt"] = pd.to_datetime(df["accessed_time_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["dt"])
    # Convert UTC -> local EDT (US/Eastern, UTC-4 during May)
    df["hour"] = (df["dt"].dt.tz_convert("US/Eastern")
                          .dt.hour.astype(int))
    df["ports_total"] = df["in_use_ports"] + df["available_ports"]
    df = df[df["ports_total"] > 0]
    df["util"] = df["in_use_ports"] / df["ports_total"]
    diurnal = (df.groupby(["station_id", "hour"])["util"]
               .mean().unstack(fill_value=0.0))
    diurnal = diurnal.reindex(columns=range(24), fill_value=0.0)
    print(f"  CP diurnal: {len(diurnal):,} stations × 24h "
          f"(from {df['dt'].min()} to {df['dt'].max()})")
    return diurnal


def pearson_r(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.std() == 0 or b.std() == 0:
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def per_cp_metrics(sim_d: pd.DataFrame, cp_d: pd.DataFrame,
                   cp_to_meta: dict) -> pd.DataFrame:
    """One row per CP facility (cp_station_id) with sim vs CP 24-h profiles.
    sim_d and cp_d are both indexed by cp_station_id so the comparison is at
    the same level of aggregation on both sides — removes the N->1 duplication
    bias from the older per-sim-station version.

    cp_to_meta is a dict cp_id -> {afdc_ids: list[str], sim_station_count: int,
    median_match_dist_m: float}, derived in main() from the joined frame."""
    out = []
    common = sim_d.index.intersection(cp_d.index)
    for cp_id in common:
        sim_p = sim_d.loc[cp_id].values.astype(float)
        cp_p = cp_d.loc[cp_id].values.astype(float)
        meta = cp_to_meta.get(int(cp_id), {})
        out.append({
            "cp_station_id":       int(cp_id),
            "afdc_ids":            "|".join(meta.get("afdc_ids", [])),
            "sim_station_count":   int(meta.get("sim_station_count", 0)),
            "median_match_dist_m": float(meta.get("median_match_dist_m", np.nan)),
            "sim_mean":            float(sim_p.mean()),
            "cp_mean":             float(cp_p.mean()),
            "sim_peak":            float(sim_p.max()),
            "cp_peak":             float(cp_p.max()),
            "sim_peak_hr":         int(sim_p.argmax()),
            "cp_peak_hr":          int(cp_p.argmax()),
            "rmse":                float(np.sqrt(np.mean((sim_p - cp_p) ** 2))),
            "pearson_r":           pearson_r(sim_p, cp_p),
            "peak_abs_err":        abs(float(sim_p.max()) - float(cp_p.max())),
        })
    return pd.DataFrame(out)


def system_diurnal_overlay(sim_d: pd.DataFrame, cp_d: pd.DataFrame,
                           cp_ids: list, out_path: Path,
                           run_label: str) -> None:
    """One overlay: mean across matched CP facilities of sim vs CP per hour."""
    s_rows, c_rows = [], []
    for cp_id in cp_ids:
        if cp_id in sim_d.index and cp_id in cp_d.index:
            s_rows.append(sim_d.loc[cp_id].values)
            c_rows.append(cp_d.loc[cp_id].values)
    if not s_rows:
        print("  [overlay] no matched stations to plot.")
        return
    sim_mean = np.mean(np.vstack(s_rows), axis=0)
    cp_mean = np.mean(np.vstack(c_rows), axis=0)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(range(24), cp_mean, "o-", color="#1f78b4",
            label=f"ChargePoint observed (n={len(c_rows)} stations)",
            linewidth=1.8, markersize=4.5)
    ax.plot(range(24), sim_mean, "s-", color="#e31a1c",
            label=f"MATSim simulated (matched, same stations)",
            linewidth=1.8, markersize=4.5)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel("Hour of day (EDT)", fontsize=11)
    ax.set_ylabel("Mean port utilization fraction", fontsize=11)
    ax.set_title(f"24-h diurnal occupancy — {run_label}\n"
                 f"averaged across matched ChargePoint MD stations",
                 fontsize=12)
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.set_ylim(0, max(0.05, max(sim_mean.max(), cp_mean.max()) * 1.15))
    ax.legend(loc="upper left", fontsize=10)
    fig.tight_layout()
    fig.savefig(out_path, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote: {out_path}")


def peak_scatter(metrics: pd.DataFrame, out_path: Path, run_label: str) -> None:
    if metrics.empty:
        return
    fig, ax = plt.subplots(figsize=(6.5, 6.5))
    ax.scatter(metrics["cp_peak"], metrics["sim_peak"],
               s=22, alpha=0.55, color="#33a02c", edgecolor="black",
               linewidth=0.4)
    m = max(metrics["cp_peak"].max(), metrics["sim_peak"].max(), 0.05)
    ax.plot([0, m], [0, m], "k--", linewidth=1.2, label="y=x (perfect)")
    ax.set_xlabel("Observed peak-hour utilization (ChargePoint)", fontsize=11)
    ax.set_ylabel("Simulated peak-hour utilization (MATSim)", fontsize=11)
    ax.set_title(f"Peak-hour port utilization — {run_label}\n"
                 f"one point per matched station (n={len(metrics)})",
                 fontsize=12)
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.set_xlim(0, m * 1.05)
    ax.set_ylim(0, m * 1.05)
    ax.set_aspect("equal", adjustable="box")
    ax.legend(loc="upper left", fontsize=10)
    fig.tight_layout()
    fig.savefig(out_path, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote: {out_path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path,
                    default=REPO_ROOT / "output" / "prod_100pct",
                    help="MATSim run output directory")
    ap.add_argument("--iter", type=int, default=None,
                    help="Iteration to validate (default: highest available)")
    ap.add_argument("--out", type=Path,
                    default=REPO_ROOT / "output" / "validation",
                    help="Output directory for CSV + PDFs")
    ap.add_argument("--match-tolerance-m", type=float, default=150.0,
                    help="Sim<->AFDC nearest-neighbor max distance (m)")
    args = ap.parse_args()

    # Resolve iter
    iters_dir = args.run / "ITERS"
    if not iters_dir.exists():
        print(f"ERROR: {iters_dir} missing.", file=sys.stderr)
        return 2
    if args.iter is None:
        it_dirs = [d for d in iters_dir.iterdir()
                   if d.name.startswith("it.") and d.name[3:].isdigit()]
        if not it_dirs:
            print("ERROR: no iteration outputs found.", file=sys.stderr)
            return 2
        args.iter = max(int(d.name[3:]) for d in it_dirs)
    print(f"[validate] run={args.run.name}  iter={args.iter}  "
          f"tol={args.match_tolerance_m:.0f}m")

    xy_gz = (iters_dir / f"it.{args.iter}"
             / f"{args.iter}.charger_occupancy_absolute.xy.gz")
    if not xy_gz.exists():
        print(f"ERROR: {xy_gz} missing.", file=sys.stderr)
        return 2

    print("[step 1] read sim chargers")
    chargers = read_sim_chargers(CHARGERS_XML)
    sim_stations = aggregate_sim_to_stations(chargers)

    print("[step 2] read AFDC catalog and CP crosswalk")
    afdc = read_afdc_md(AFDC_CSV)
    afdc_proj = project_afdc_to_sim_crs(afdc)
    crosswalk = read_crosswalk(CP_DB)

    print("[step 3] join sim<->AFDC<->CP")
    joined = join_sim_to_afdc(sim_stations, afdc_proj, args.match_tolerance_m)
    joined = joined.merge(crosswalk, left_on="afdc_id",
                          right_on="afdc_station_id", how="inner")
    print(f"  sim<->CP joined: {len(joined):,}  "
          f"(distinct sim stations: {joined.sim_station_idx.nunique():,}, "
          f"distinct CP: {joined.cp_station_id.nunique():,})")
    if joined.empty:
        print("ERROR: no sim<->CP joins; check tolerance or coordinate CRS.",
              file=sys.stderr)
        return 2

    # Build sim_id -> cp_id mapping. Each sim station (unique x,y) can hold
    # multiple sim charger ids; all of them map to the same cp_station_id.
    sim_id_to_cp: dict = {}
    cp_to_meta: dict = defaultdict(lambda: {
        "afdc_ids": [], "sim_station_count": 0,
        "match_dists": [],
    })
    for _, r in joined.iterrows():
        cp_id = int(r["cp_station_id"])
        for sid in r["sim_ids"]:
            sim_id_to_cp[sid] = cp_id
        cp_to_meta[cp_id]["afdc_ids"].append(str(r["afdc_id"]))
        cp_to_meta[cp_id]["sim_station_count"] += 1
        cp_to_meta[cp_id]["match_dists"].append(float(r["afdc_match_dist_m"]))
    # Reduce match_dists to median for the summary CSV
    cp_to_meta_final = {}
    for cp_id, m in cp_to_meta.items():
        cp_to_meta_final[cp_id] = {
            "afdc_ids":            sorted(set(m["afdc_ids"])),
            "sim_station_count":   m["sim_station_count"],
            "median_match_dist_m": float(np.median(m["match_dists"])),
        }
    print(f"  sim_id -> cp_id entries: {len(sim_id_to_cp):,}  "
          f"distinct CP facilities: {len(cp_to_meta_final):,}")

    print(f"[step 4] read sim occupancy ({xy_gz.name})")
    sim_occ = read_sim_occupancy(xy_gz)
    sim_d = sim_diurnal_by_cp(sim_occ, sim_id_to_cp)
    print(f"  sim diurnal: {len(sim_d):,} CP facilities × 24h")

    print("[step 5] read CP diurnal observations")
    cp_d = cp_diurnal(CP_DB, set(joined["cp_station_id"].astype(int).tolist()))
    if cp_d.empty:
        print("ERROR: no CP observations for joined stations.", file=sys.stderr)
        return 2

    print("[step 6] per-CP-facility metrics")
    metrics = per_cp_metrics(sim_d, cp_d, cp_to_meta_final)
    metrics = metrics.dropna(subset=["pearson_r"])
    args.out.mkdir(parents=True, exist_ok=True)
    metrics_csv = args.out / "chargepoint_validation_summary.csv"
    metrics.to_csv(metrics_csv, index=False)
    print(f"  wrote: {metrics_csv}  ({len(metrics):,} matched CP facilities)")

    print("\n[results]")
    print(f"  matched CP facilities:   {len(metrics):,}")
    print(f"  median Pearson r:        {metrics.pearson_r.median():.3f}")
    print(f"  mean Pearson r:          {metrics.pearson_r.mean():.3f}")
    print(f"  median RMSE (util frac): {metrics.rmse.median():.3f}")
    print(f"  median peak-hr abs err:  {metrics.peak_abs_err.median():.3f}")
    print(f"  sim mean util (matched): {metrics.sim_mean.mean():.3f}")
    print(f"  CP  mean util (matched): {metrics.cp_mean.mean():.3f}")

    print("\n[plots]")
    cp_ids = metrics["cp_station_id"].astype(int).tolist()
    system_diurnal_overlay(sim_d, cp_d, cp_ids,
                           args.out / "chargepoint_diurnal_overlay.pdf",
                           f"{args.run.name} it.{args.iter}")
    peak_scatter(metrics,
                 args.out / "chargepoint_peak_scatter.pdf",
                 f"{args.run.name} it.{args.iter}")
    print("\n[done]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
