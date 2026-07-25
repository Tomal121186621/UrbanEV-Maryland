#!/usr/bin/env python3
"""
network_map.py — publication two-layer EV traffic-flow map of Maryland (fast; uses the
saved per-link VMT, no events re-parse). Layer 1: full network in light grey (context).
Layer 2: links carrying meaningful EV VMT, coloured + width-weighted by VMT. County
boundaries basemap; clean map frame (no coordinate ticks).
"""
import sys, gzip
from pathlib import Path
import numpy as np, pandas as pd, xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import LogNorm
import geopandas as gpd

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
B = ROOT / "scenarios/maryland/output/runs_2026" / (sys.argv[1] if len(sys.argv) > 1 else "baseline")
NET = REPO / "Input/network/maryland-network-pt2matsim.xml.gz"
TRACT = REPO / "pipeline/data/geo/tl_2020_24_tract.shp"
OUT = B / "route_analysis"


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


def main():
    g = geom()
    v = pd.read_parquet(OUT / "link_vmt.parquet")
    g = g.join(v)
    g["vmt"] = g.vmt.fillna(0)
    seg = lambda df: np.stack([df[["x1", "y1"]].to_numpy(), df[["x2", "y2"]].to_numpy()], axis=1)

    cty = gpd.read_file(TRACT); cty["c"] = cty.GEOID.str[:5]
    cty = cty.dissolve("c").to_crs("EPSG:26985")

    thr = 300                                            # mi/day: below = context only
    base = g[g.vmt <= thr]; flow = g[g.vmt > thr].sort_values("vmt")
    fv = flow.vmt.to_numpy()
    lo, hi = np.percentile(fv, 20), np.percentile(fv, 99.0)

    fig, ax = pf.newfig(7.4, 8.2)
    cty.plot(ax=ax, facecolor="#f4f4f2", edgecolor="0.7", lw=0.5, zorder=0)
    ax.add_collection(LineCollection(seg(base), colors="0.72", linewidths=0.12, zorder=1))
    lc = LineCollection(seg(flow), cmap="plasma", norm=LogNorm(lo, hi),
                        linewidths=np.clip(0.3 + (fv / hi) * 3.0, 0.3, 3.4), zorder=2, capstyle="round")
    lc.set_array(fv); ax.add_collection(lc)
    ax.set_title("Simulated EV vehicle-miles by road link — Maryland, 2026", pad=8)
    ax.set_aspect("equal"); ax.autoscale(); ax.axis("off")
    cb = fig.colorbar(lc, ax=ax, shrink=0.55, pad=0.01)
    cb.set_label("EV VMT per link (mi/day)")
    # scale-bar (20 km)
    x0, y0 = ax.get_xlim()[0] + 8000, ax.get_ylim()[0] + 12000
    ax.plot([x0, x0 + 20000], [y0, y0], color="k", lw=2)
    ax.text(x0 + 10000, y0 + 3000, "20 km", ha="center", fontsize=8)
    pf.save(fig, OUT, "network_vmt_map")
    print(f"[done] flow map -> {OUT}/network_vmt_map.png  (flow links={len(flow):,}, base={len(base):,})")


if __name__ == "__main__":
    main()
