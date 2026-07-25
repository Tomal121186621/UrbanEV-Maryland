#!/usr/bin/env python3
"""
route_analysis.py — CONGESTION-INDEPENDENT route/trajectory analysis for the EV-only
simulation, culminating in a publication network-flow map of Maryland. Travel times are
free-flow (EVs only, no background traffic) and are NOT used; every metric is
distance/energy/spatial — valid regardless of congestion.

  1. per-link EV VMT (link-traversal events x link length)  -> saved parquet
  2. VMT by road class (interstate/arterial/collector/local)
  3. NETWORK FLOW MAP: Maryland road network, links coloured + weighted by EV VMT,
     county boundaries basemap (EPSG:26985)
  4. shadow gas-tax gap by home county
"""
import sys, gzip, re
from pathlib import Path
from collections import Counter
import numpy as np, pandas as pd
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import LogNorm

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
B = ROOT / "scenarios/maryland/output/runs_2026" / (sys.argv[1] if len(sys.argv) > 1 else "baseline")
NET = REPO / "Input/network/maryland-network-pt2matsim.xml.gz"
RC = REPO / "Input/network/link_road_class.parquet"
EVO = REPO / "pipeline/data/interim/ev_owners.parquet"
TRACT = REPO / "pipeline/data/geo/tl_2020_24_tract.shp"
OUT = B / "route_analysis"; PAPER = REPO / "paper"
N_DAYS = 3


def parse_network():
    nodes = {}; rows = []
    for ev, el in ET.iterparse(gzip.open(NET, "rt"), events=("end",)):
        if el.tag == "node":
            nodes[el.get("id")] = (float(el.get("x")), float(el.get("y")))
        elif el.tag == "link":
            f, t = nodes.get(el.get("from")), nodes.get(el.get("to"))
            if f and t:
                rows.append((el.get("id"), f[0], f[1], t[0], t[1], float(el.get("length", 0))))
            el.clear()
    return pd.DataFrame(rows, columns=["link", "x1", "y1", "x2", "y2", "length"]).set_index("link")


def link_counts():
    cnt = Counter(); lp = re.compile(r'link="([^"]+)"')
    print("[events] streaming left-link events ...", flush=True)
    with gzip.open(B / "output_events.xml.gz", "rt") as f:
        for ln in f:
            if 'type="left link"' in ln:
                m = lp.search(ln)
                if m:
                    cnt[m.group(1)] += 1
    return cnt


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    net = parse_network()
    rc = pd.read_parquet(RC)
    cnt = link_counts()
    net["trav"] = net.index.map(lambda l: cnt.get(l, 0))
    net["vmt"] = net.trav * net.length / 1609.344 / N_DAYS       # mi/day per link
    net["road_class"] = rc.road_class.reindex(net.index).fillna("other")
    net[["vmt", "road_class"]].to_parquet(OUT / "link_vmt.parquet")

    # ---- VMT by road class ----
    vmt = net.groupby("road_class").vmt.sum().sort_values(ascending=False)
    order = [c for c in ["interstate", "arterial", "collector", "local", "other"] if c in vmt.index]
    vmt = vmt.reindex(order)
    fig, ax = pf.newfig(5.6, 3.6)
    ax.bar(vmt.index, vmt.values / vmt.sum() * 100, color=pf.BLUE, edgecolor="k", lw=0.4)
    ax.set(ylabel="% of daily EV VMT", title="EV VMT by road class")
    for t in ax.get_xticklabels(): t.set_rotation(15); t.set_ha("right")
    pf.save(fig, OUT, "vmt_by_road_class")
    vmt.rename("vmt_mi_day").to_csv(PAPER / "tables/vmt_by_road_class.csv")
    print("[VMT by class] mi/day:", {k: int(v) for k, v in vmt.items()})

    # ---- NETWORK FLOW MAP ----
    import geopandas as gpd
    cty = gpd.read_file(TRACT)
    cty["cfips"] = cty.GEOID.str[:5]
    cty = cty.dissolve("cfips").to_crs("EPSG:26985")
    used = net[net.vmt > 0].copy()
    used = used.sort_values("vmt")                              # draw busy links last (on top)
    segs = np.stack([used[["x1", "y1"]].to_numpy(), used[["x2", "y2"]].to_numpy()], axis=1)
    v = used.vmt.to_numpy(); v = np.clip(v, 1, None)
    fig, ax = pf.newfig(7.2, 8)
    cty.boundary.plot(ax=ax, color="0.75", lw=0.4, zorder=1)
    lc = LineCollection(segs, cmap="inferno", norm=LogNorm(vmt.min() + 1, np.percentile(v, 99.5)),
                        linewidths=np.clip(0.15 + v / np.percentile(v, 99) * 1.6, 0.15, 2.2), zorder=2)
    lc.set_array(v); ax.add_collection(lc)
    ax.set(title="Simulated EV vehicle-miles by road link, Maryland 2026", xlabel="easting (m)", ylabel="northing (m)")
    ax.set_aspect("equal"); ax.autoscale()
    fig.colorbar(lc, ax=ax, label="EV VMT per link (mi/day, log)", shrink=0.6)
    pf.save(fig, OUT, "network_vmt_map")

    # ---- shadow gap by county ----
    pa = pd.read_csv(B / "shadow_tax_gap_per_agent.csv")
    pa["fips"] = pd.read_parquet(EVO).set_index("person_id").home_county.reindex(pa.vehicle_id).values
    g = pa.groupby("fips").agg(shadow=("state_tax_gap_day_usd", "sum")).assign(
        shadow_yr_M=lambda x: x.shadow * 348 / 1e6).sort_values("shadow_yr_M").tail(12)
    fig, ax = pf.newfig(6, 4.4)
    ax.barh([str(int(f))[-3:] for f in g.index], g.shadow_yr_M, color=pf.GREEN, edgecolor="k", lw=0.3)
    ax.set(xlabel="annual shadow gap ($M)", title="Shadow gas-tax gap by home county (top 12)")
    pf.save(fig, OUT, "shadow_gap_by_county")
    print(f"[done] network map + 3 figures -> {OUT}")


if __name__ == "__main__":
    main()
