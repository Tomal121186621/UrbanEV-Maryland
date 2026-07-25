#!/usr/bin/env python3
"""
analyze_all_policies.py — generate the COMPLETE analysis suite for every policy run.
Waits for the 100% policy sweep to finish, then for each scenario produces charging
profiles + road-class VMT + network flow map, runs the combined winners/losers/revenue
framework and incidence figures, and builds policy-vs-baseline VMT DIFFERENCE maps.
"""
import subprocess, time, glob, sys, gzip
from pathlib import Path
import numpy as np, pandas as pd, xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import TwoSlopeNorm

A = Path(__file__).resolve().parent
ROOT = A.parent; REPO = ROOT.parent
RUNS = ROOT / "scenarios/maryland/output/runs_2026"
PY = str(REPO / ".venv/bin/python")
NET = REPO / "Input/network/maryland-network-pt2matsim.xml.gz"
TRACT = REPO / "pipeline/data/geo/tl_2020_24_tract.shp"
SCEN = pd.read_csv(A / "policy_scenarios.csv").scenario_id.tolist()
RUNDIRS = [f"policy_{s}_100pct" for s in SCEN]


def is_done(r):
    # output_events.xml.gz is only written at MATSim shutdown -> definitive completion
    return (RUNS / r / "output_events.xml.gz").exists()


def wait():
    print("[analyze] waiting for policy sweep to COMPLETE ...", flush=True)
    while not all(is_done(r) for r in RUNDIRS):
        time.sleep(300)
    time.sleep(90)


def geom():
    nodes = {}; rows = []
    for _, el in ET.iterparse(gzip.open(NET, "rt"), events=("end",)):
        if el.tag == "node":
            nodes[el.get("id")] = (float(el.get("x")), float(el.get("y")))
        elif el.tag == "link":
            f, t = nodes.get(el.get("from")), nodes.get(el.get("to"))
            if f and t:
                rows.append((el.get("id"), f[0], f[1], t[0], t[1]))
            el.clear()
    return pd.DataFrame(rows, columns=["link", "x1", "y1", "x2", "y2"]).set_index("link")


def diff_map(run, g, base_vmt, cty):
    pv = pd.read_parquet(RUNS / run / "route_analysis/link_vmt.parquet").vmt
    d = (pv.reindex(g.index).fillna(0) - base_vmt.reindex(g.index).fillna(0))
    gg = g.assign(d=d)
    sig = gg[gg.d.abs() > 20].sort_values("d", key=abs)
    seg = np.stack([sig[["x1", "y1"]].to_numpy(), sig[["x2", "y2"]].to_numpy()], axis=1)
    lim = np.percentile(sig.d.abs(), 99)
    fig, ax = pf.newfig(7.2, 8)
    cty.plot(ax=ax, facecolor="#f6f6f4", edgecolor="0.7", lw=0.4, zorder=0)
    lc = LineCollection(seg, cmap="RdBu_r", norm=TwoSlopeNorm(0, -lim, lim),
                        linewidths=np.clip(0.3 + sig.d.abs() / lim * 2.5, 0.3, 3), zorder=2)
    lc.set_array(sig.d.to_numpy()); ax.add_collection(lc)
    ax.set_title(f"EV VMT shift under {run.replace('policy_', '').replace('_100pct', '')}\n(red = more, blue = less vs baseline)", fontsize=11)
    ax.set_aspect("equal"); ax.autoscale(); ax.axis("off")
    fig.colorbar(lc, ax=ax, label="Δ EV VMT per link (mi/day)", shrink=0.55)
    pf.save(fig, RUNS / run / "route_analysis", "network_vmt_diff_map")


def main():
    if "--now" not in sys.argv:
        wait()
    runs = [r for r in RUNDIRS if is_done(r)]
    print(f"[analyze] {len(runs)} policy runs ready", flush=True)
    for r in runs:                                         # per-scenario full suite
        subprocess.run([PY, str(A / "charging_profiles.py"), r])
        subprocess.run([PY, str(A / "route_analysis.py"), r])
        subprocess.run([PY, str(A / "network_map.py"), r])
    subprocess.run([PY, str(A / "policy_framework.py")])   # combined winners/losers/revenue
    subprocess.run([PY, str(A / "incidence_analysis.py")])
    # difference maps (need geometry + baseline link VMT once)
    g = geom()
    base_vmt = pd.read_parquet(RUNS / "baseline/route_analysis/link_vmt.parquet").vmt
    import geopandas as gpd
    cty = gpd.read_file(TRACT); cty["k"] = cty.GEOID.str[:5]; cty = cty.dissolve("k").to_crs("EPSG:26985")
    for r in runs:
        diff_map(r, g, base_vmt, cty)
    print("[analyze] complete — per-policy profiles, maps, diff-maps + combined framework")


if __name__ == "__main__":
    main()
