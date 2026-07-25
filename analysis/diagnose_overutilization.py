#!/usr/bin/env python3
"""
diagnose_overutilization.py — diagnose why sim utilization is ~2.1x observed.

Hypotheses tested:
  H1. Per-type bias: is over-util concentrated in one charger type (L2 vs DCFC)?
  H2. Plug-count miscount: sim ports/station vs AFDC-reported ports/station
  H3. Session length: sim session durations vs typical real-world (EVWatts)
  H4. Hour-of-day shape: when is the gap largest?
  H5. Long-tail stations: are a few sim stations dominating the mean?
  H6. CP availability denominator: how many ports does CP report vs sim allots?

Reads:
  output/prod_100pct/ITERS/it.36/36.charging_sessions.csv
  output/prod_100pct/ITERS/it.36/36.charger_type_occupancy_time_profiles.txt
  output/prod_100pct/ITERS/it.36/36.charger_occupancy_absolute.xy.gz
  output/validation/chargepoint_validation_summary.csv
  Input/chargers/chargers.xml
  Baseline Validation/Data/.../chargepoint_md.db
  Baseline Validation/Data/.../alt_fuel_stations (Jan 19 2026).csv
"""
from __future__ import annotations
import csv
import gzip
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = REPO_ROOT.parent
DATA_DIR = PROJECT_ROOT / "Baseline Validation" / "Data" / "ChargePoint Data Collection"
RUN_DIR = REPO_ROOT / "output" / "prod_100pct"
IT_DIR = RUN_DIR / "ITERS" / "it.36"
SESSIONS_CSV = IT_DIR / "36.charging_sessions.csv"
TYPE_PROFILE_TXT = IT_DIR / "36.charger_type_occupancy_time_profiles.txt"
XY_GZ = IT_DIR / "36.charger_occupancy_absolute.xy.gz"
CHARGERS_XML = PROJECT_ROOT / "Input" / "chargers" / "chargers.xml"
AFDC_CSV = DATA_DIR / "alt_fuel_stations (Jan 19 2026).csv"
CP_DB = DATA_DIR / "chargepoint_md.db"
VAL_CSV = REPO_ROOT / "output" / "validation" / "chargepoint_validation_summary.csv"

SIM_CRS = "EPSG:26985"
LATLON_CRS = "EPSG:4326"

# -----------------------------------------------------------------------------
def hdr(s):
    print("\n" + "=" * 72)
    print(s)
    print("=" * 72)

# -----------------------------------------------------------------------------
def read_chargers():
    root = ET.parse(CHARGERS_XML).getroot()
    rows = []
    for c in root.findall("charger"):
        rows.append({
            "sim_id":     c.get("id"),
            "ctype":      c.get("type"),
            "x":          float(c.get("x")),
            "y":          float(c.get("y")),
            "plug_count": int(c.get("plug_count") or 1),
            "plug_power": float(c.get("plug_power") or 0.0),
        })
    return pd.DataFrame(rows)

def read_afdc():
    rows = []
    with AFDC_CSV.open(encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            if row.get("State") != "MD" or row.get("Fuel Type Code") != "ELEC":
                continue
            try:
                lat = float(row["Latitude"]); lon = float(row["Longitude"])
            except (TypeError, ValueError, KeyError):
                continue
            def _i(s):
                try: return int(s)
                except (TypeError, ValueError): return 0
            rows.append({
                "afdc_id":   row.get("ID"),
                "lat": lat, "lon": lon,
                "ev_l2":    _i(row.get("EV Level2 EVSE Num")),
                "ev_dcfc":  _i(row.get("EV DC Fast Count")),
                "network":  row.get("EV Network") or "",
            })
    return pd.DataFrame(rows)

def project_to_sim(df):
    t = Transformer.from_crs(LATLON_CRS, SIM_CRS, always_xy=True)
    x, y = t.transform(df["lon"].values, df["lat"].values)
    df = df.copy(); df["x_proj"] = x; df["y_proj"] = y
    return df

# -----------------------------------------------------------------------------
def h1_per_type():
    hdr("H1: per-type sim vs CP utilization")
    # Sim per-type 24-h profile from 5-min file
    df = pd.read_csv(TYPE_PROFILE_TXT, sep="\t")
    df.columns = [c.strip() for c in df.columns]
    # Sum per type across day, normalize by sum of plugs of that type for util
    chargers = read_chargers()
    plugs_by_type = chargers.groupby("ctype")["plug_count"].sum().to_dict()
    print(f"  plugs by type: {plugs_by_type}")
    for typ in ["home", "work", "L2", "DCFC", "DCFC_TESLA"]:
        if typ not in df.columns:
            continue
        mean_plugged = df[typ].mean()
        # The .txt is # of plugged in-use chargers at each 5-min slot
        denom = plugs_by_type.get(typ, 0)
        if denom == 0 and typ in ("home", "work"):
            # home/work have no entries in chargers.xml — Parishwad's per-person
            # home charger lives off-network. Just report absolute count.
            print(f"  sim {typ:10s} mean concurrent = {mean_plugged:>10,.0f}  (no plug pool)")
        else:
            util = mean_plugged / denom if denom else 0.0
            print(f"  sim {typ:10s} mean concurrent = {mean_plugged:>10,.0f}  / "
                  f"{denom:>6,d} plugs = util {util:.3f}  peak {df[typ].max()/denom:.3f}")

    # CP per-type via crosswalk: read summary, join cp_id -> AFDC -> ev_l2/ev_dcfc
    val = pd.read_csv(VAL_CSV)
    afdc = read_afdc()
    # Re-derive cp_id -> dominant AFDC type
    # val.afdc_ids is "id1|id2|..."
    primary_type = []
    for ids_str in val["afdc_ids"].fillna(""):
        ids = ids_str.split("|") if ids_str else []
        sub = afdc[afdc["afdc_id"].isin(ids)]
        if sub.empty:
            primary_type.append("?")
        elif sub["ev_dcfc"].sum() > sub["ev_l2"].sum():
            primary_type.append("DCFC")
        else:
            primary_type.append("L2")
    val["facility_type"] = primary_type
    print()
    print("  per-CP-facility means (matched to sim):")
    print(val.groupby("facility_type")[["sim_mean", "cp_mean"]].agg(["count", "mean"]))

# -----------------------------------------------------------------------------
def h2_plug_count_match():
    hdr("H2: plug counts — sim vs AFDC at matched stations")
    chargers = read_chargers()
    sim_stn = chargers.groupby(["x", "y"], as_index=False).agg(
        plug_count=("plug_count", "sum"),
        ctypes=("ctype", lambda s: sorted(set(s))),
    )
    afdc = read_afdc()
    afdc_p = project_to_sim(afdc)
    tree = cKDTree(np.c_[afdc_p["x_proj"], afdc_p["y_proj"]])
    dist, idx = tree.query(np.c_[sim_stn["x"], sim_stn["y"]], k=1)
    sim_stn["afdc_id"] = afdc_p["afdc_id"].values[idx]
    sim_stn["afdc_l2"] = afdc_p["ev_l2"].values[idx]
    sim_stn["afdc_dcfc"] = afdc_p["ev_dcfc"].values[idx]
    sim_stn["match_m"] = dist
    matched = sim_stn[sim_stn["match_m"] <= 150].copy()
    matched["afdc_total"] = matched["afdc_l2"] + matched["afdc_dcfc"]
    print(f"  matched stations: {len(matched):,}")
    print(f"  sim plug_count   median = {matched.plug_count.median():.1f}  "
          f"mean = {matched.plug_count.mean():.2f}  max = {matched.plug_count.max()}")
    print(f"  AFDC ports total median = {matched.afdc_total.median():.1f}  "
          f"mean = {matched.afdc_total.mean():.2f}  max = {matched.afdc_total.max()}")
    matched["ratio"] = np.where(matched.afdc_total > 0,
                                matched.plug_count / matched.afdc_total, np.nan)
    print(f"  sim/AFDC plug ratio   median = {matched.ratio.median():.2f}  "
          f"mean = {matched.ratio.mean():.2f}")
    # If sim has FEWER plugs than AFDC, denom is smaller -> util inflated
    underplug = matched[matched.ratio < 0.5]
    print(f"  stations w/ sim < 0.5x AFDC plugs: {len(underplug):,} "
          f"({100*len(underplug)/len(matched):.1f}%)")

# -----------------------------------------------------------------------------
def h3_session_length():
    hdr("H3: sim session lengths vs typical observed")
    df = pd.read_csv(SESSIONS_CSV, sep=";")
    df["dur_min"] = df["duration_s"] / 60.0
    print(f"  total sim sessions: {len(df):,}")
    print(f"  by charger_type:")
    print(df.groupby("charger_type")["dur_min"].describe(percentiles=[0.5, 0.75, 0.95])[["count", "mean", "50%", "75%", "95%"]])
    print()
    print(f"  energy delivered (kWh) by type:")
    print(df.groupby("charger_type")["energy_kwh"].describe(percentiles=[0.5, 0.75, 0.95])[["count", "mean", "50%", "75%", "95%"]])
    print()
    # EVWatts MD typical reference (from prior runs; documented):
    # L2: median session ~150 min, median 8 kWh; DCFC: median 25 min, ~15 kWh
    print("  EVWatts MD reference (rough):  L2 ~150 min/8 kWh, DCFC ~25 min/15 kWh")

# -----------------------------------------------------------------------------
def h4_hour_shape():
    hdr("H4: hour-of-day shape — where is the gap?")
    val = pd.read_csv(VAL_CSV)
    # Re-read sim & CP diurnals from xy.gz and DB (slow but authoritative)
    print("  (skipping deep re-read; summary CSV only has scalars per station)")
    print(f"  median sim_mean   = {val.sim_mean.median():.3f}")
    print(f"  median cp_mean    = {val.cp_mean.median():.3f}")
    print(f"  median sim_peak   = {val.sim_peak.median():.3f}")
    print(f"  median cp_peak    = {val.cp_peak.median():.3f}")
    print(f"  ratio peak/mean sim = {val.sim_peak.median()/max(val.sim_mean.median(),1e-9):.2f}")
    print(f"  ratio peak/mean CP  = {val.cp_peak.median()/max(val.cp_mean.median(),1e-9):.2f}")
    print(f"  sim peak hour mode  = {val.sim_peak_hr.mode().tolist()}")
    print(f"  CP  peak hour mode  = {val.cp_peak_hr.mode().tolist()}")

# -----------------------------------------------------------------------------
def h5_long_tail():
    hdr("H5: long-tail stations driving sim mean")
    val = pd.read_csv(VAL_CSV).sort_values("sim_mean", ascending=False)
    print(f"  top 10 sim-mean (over-util) stations:")
    print(val[["cp_station_id", "sim_mean", "cp_mean", "sim_station_count",
               "pearson_r"]].head(10).to_string(index=False))
    print()
    print(f"  fraction of sim_mean concentration:")
    val_sorted = val["sim_mean"].sort_values(ascending=False)
    for pct in [0.1, 0.2, 0.5]:
        n = max(1, int(pct * len(val_sorted)))
        share = val_sorted.head(n).sum() / val_sorted.sum()
        print(f"    top {pct*100:.0f}% of stations carry {share*100:.1f}% of sim_mean")
    print()
    print(f"  stations with cp_mean == 0 (no observed activity):")
    z = val[val.cp_mean == 0]
    print(f"    n = {len(z)}; their sim_mean   median = {z.sim_mean.median():.3f}, "
          f"mean = {z.sim_mean.mean():.3f}")

# -----------------------------------------------------------------------------
def h6_cp_denominator():
    hdr("H6: CP availability denominator — are ports reported reliably?")
    con = sqlite3.connect(CP_DB)
    q = """SELECT station_id,
                  AVG(in_use_ports + available_ports) AS mean_ports_total,
                  MAX(in_use_ports + available_ports) AS max_ports_total,
                  MIN(in_use_ports + available_ports) AS min_ports_total,
                  COUNT(*) AS n_snaps,
                  AVG(in_use_ports * 1.0 /
                      NULLIF(in_use_ports + available_ports, 0)) AS mean_util
           FROM charging_session_v2
           GROUP BY station_id"""
    cp = pd.read_sql_query(q, con)
    con.close()
    print(f"  CP stations w/ obs: {len(cp):,}")
    print(f"  mean ports/station reported:  median = {cp.mean_ports_total.median():.1f}, "
          f"max = {cp.max_ports_total.max():.0f}")
    print(f"  CP per-station mean util:     median = {cp.mean_util.median():.3f}")
    # Compare against val
    val = pd.read_csv(VAL_CSV)
    cp.rename(columns={"station_id": "cp_station_id"}, inplace=True)
    m = val.merge(cp, on="cp_station_id", how="left")
    print(f"  matched CP stations: {len(m):,}")
    print(f"  AFDC says {m['sim_station_count'].mean():.2f} sim stations / cp facility (mean)")

# -----------------------------------------------------------------------------
def main():
    if not VAL_CSV.exists():
        print(f"ERROR: run validate_vs_chargepoint.py first ({VAL_CSV} missing)",
              file=sys.stderr); return 2
    h1_per_type()
    h2_plug_count_match()
    h3_session_length()
    h4_hour_shape()
    h5_long_tail()
    h6_cp_denominator()
    return 0

if __name__ == "__main__":
    sys.exit(main())
