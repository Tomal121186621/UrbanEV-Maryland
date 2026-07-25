#!/usr/bin/env python3
"""Clean Maryland study-area map: quantile-binned EV-owners choropleth + DC-fast chargers
(the corridor-relevant fast chargers; 1,391 Level-2 omitted for legibility). One combined
legend in the empty lower-left. Uniform pubfig palette. Real data only."""
import sys; sys.path.insert(0, "UrbanEV-Maryland/analysis")
import pubfig as pf
import numpy as np, pandas as pd, geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
from matplotlib.colors import BoundaryNorm
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")

# counties (dissolve tracts) in MD state plane
tr = gpd.read_file(REPO / "pipeline/data/geo/tl_2020_24_tract.shp")[["GEOID", "geometry"]]
tr["fips"] = tr.GEOID.str[:5]
cty = tr.dissolve("fips").reset_index().to_crs(26985)
assert cty.fips.nunique() == 24, cty.fips.nunique()

# EV owners per county
ev = pd.read_parquet(REPO / "pipeline/data/interim/ev_owners.parquet")
cnt = ev.home_county.astype(int).value_counts()
cty["ev"] = cty.fips.astype(int).map(cnt).fillna(0).astype(int)
state = cty.dissolve()

# chargers: L2 (dense -> small translucent dots) and DC-fast (bold triangles on top)
dx, dy, lx, ly = [], [], [], []
for el in ET.parse(REPO / "Input/chargers/chargers.xml").getroot():
    t = el.get("type")
    if t in ("DCFC", "DCFC_TESLA"):
        dx.append(float(el.get("x"))); dy.append(float(el.get("y")))
    elif t == "L2":
        lx.append(float(el.get("x"))); ly.append(float(el.get("y")))
n_l2 = len(lx)

# quantile bins (5 classes)
edges = np.unique(np.quantile(cty.ev, [0, .2, .4, .6, .8, 1.0]).round().astype(int))
cmap = plt.get_cmap("Blues")
norm = BoundaryNorm(edges, ncolors=cmap.N)

fig, ax = pf.newfig(7.6, 7.4)
ax.grid(False)
cty.plot(column="ev", cmap=cmap, norm=norm, ax=ax, edgecolor="white", linewidth=0.7)
state.boundary.plot(ax=ax, color="#1a1a1a", linewidth=1.7)
ax.scatter(lx, ly, marker="o", s=6, facecolor=pf.ORANGE, edgecolor="none", alpha=0.45, zorder=5)
ax.scatter(dx, dy, marker="^", s=26, facecolor=pf.VERM, edgecolor="k", linewidth=0.35, zorder=6)
ax.set_axis_off(); ax.set_aspect("equal")
ax.set_title("Maryland study area: EV owners by county and public charging", fontsize=12.5)

# one combined legend (bins + charger markers), lower-left empty area
h = [mpatches.Patch(facecolor=cmap(norm((edges[i] + edges[i + 1]) / 2)), edgecolor="white",
                    label=f"{edges[i]:,}–{edges[i+1]:,}") for i in range(len(edges) - 1)]
h.append(Line2D([0], [0], marker="o", color="none", markerfacecolor=pf.ORANGE, markeredgecolor="none",
                markersize=7, alpha=0.6, label=f"Level-2 charger (n={n_l2:,})"))
h.append(Line2D([0], [0], marker="^", color="none", markerfacecolor=pf.VERM, markeredgecolor="k",
                markersize=8, label=f"DC-fast charger (n={len(dx)})"))
ax.legend(handles=h, title="EV owners / county", loc="lower left", fontsize=8.5,
          title_fontsize=9.5, frameon=True, framealpha=0.95, borderpad=0.7)

# scale bar (20 km) in lower-right
x0, x1, y0, y1 = *ax.get_xlim(), *ax.get_ylim()
sx = x1 - (x1 - x0) * 0.26; sy = y0 + (y1 - y0) * 0.05
ax.plot([sx, sx + 20000], [sy, sy], color="k", lw=2.2)
ax.text(sx + 10000, sy + (y1 - y0) * 0.012, "20 km", ha="center", fontsize=8)

pf.save(fig, "paper/figures", "study_area")
print(f"[done] DCFC {len(dx)} plotted; L2 {n_l2} omitted; EV/county {cty.ev.min()}–{cty.ev.max()}; bins {list(edges)}")
