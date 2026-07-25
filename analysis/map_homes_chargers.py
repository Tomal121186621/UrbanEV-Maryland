#!/usr/bin/env python3
"""
map_homes_chargers.py — publication map of EV-owner home density and public charging
stations across Maryland. Background: EV-home density (hexbin, log). Overlay: public
chargers coloured by type (L2 vs DCFC), sized by plug count. County boundaries basemap.
"""
import sys, re
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
import geopandas as gpd

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
EVO = REPO / "pipeline/data/interim/ev_owners.parquet"
CHG = REPO / "Input/chargers/chargers.xml"
TRACT = REPO / "pipeline/data/geo/tl_2020_24_tract.shp"
OUT = ROOT / "scenarios/maryland/output/runs_2026/baseline/route_analysis"


def main():
    ev = pd.read_parquet(EVO)
    hx = pd.to_numeric(ev.home_x, errors="coerce"); hy = pd.to_numeric(ev.home_y, errors="coerce")
    ok = hx.notna() & hy.notna()

    txt = CHG.read_text()
    rows = re.findall(r'type="([^"]+)"[^>]*plug_count="(\d+)"[^>]*x="([-0-9.]+)"[^>]*y="([-0-9.]+)"', txt)
    c = pd.DataFrame(rows, columns=["type", "plugs", "x", "y"])
    c[["plugs", "x", "y"]] = c[["plugs", "x", "y"]].apply(pd.to_numeric)
    c["grp"] = np.where(c.type.str.contains("DCFC"), "DCFC", np.where(c.type == "L2", "L2", "L1"))

    cty = gpd.read_file(TRACT); cty["k"] = cty.GEOID.str[:5]
    cty = cty.dissolve("k").to_crs("EPSG:26985")

    fig, ax = pf.newfig(7.6, 8.2)
    cty.plot(ax=ax, facecolor="#f6f6f4", edgecolor="0.7", lw=0.5, zorder=0)
    hb = ax.hexbin(hx[ok], hy[ok], gridsize=55, cmap="Blues", bins="log", mincnt=1,
                   zorder=1, alpha=0.9, linewidths=0)
    l2 = c[c.grp == "L2"]; dc = c[c.grp == "DCFC"]
    ax.scatter(l2.x, l2.y, s=6 + l2.plugs * 1.2, c="#009E73", edgecolor="k", lw=0.15,
               alpha=0.8, zorder=3, label=f"L2 station (n={len(l2)})")
    ax.scatter(dc.x, dc.y, s=14 + dc.plugs * 1.5, marker="^", c="#D55E00", edgecolor="k",
               lw=0.2, alpha=0.9, zorder=4, label=f"DCFC station (n={len(dc)})")
    ax.set_title("EV-owner homes and public charging — Maryland 2026", fontsize=12, pad=6)
    ax.set_aspect("equal"); ax.autoscale(); ax.axis("off")
    ax.legend(loc="upper left", markerscale=1.2, fontsize=9)      # empty western panhandle
    cb = fig.colorbar(hb, ax=ax, shrink=0.5, pad=0.01); cb.set_label("EV-owner homes per cell (log)")
    x0, y0 = ax.get_xlim()[0] + 8000, ax.get_ylim()[0] + 14000    # scale bar lower-left, clear
    ax.plot([x0, x0 + 20000], [y0, y0], color="k", lw=2); ax.text(x0 + 10000, y0 + 3500, "20 km", ha="center", fontsize=8)
    pf.save(fig, OUT, "homes_and_chargers_map")
    print(f"[done] {ok.sum():,} EV homes, {len(l2)} L2 + {len(dc)} DCFC stations -> {OUT}/homes_and_chargers_map.png")


if __name__ == "__main__":
    main()
