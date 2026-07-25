#!/usr/bin/env python3
"""Publication map of the AADT-loaded time-variant network (v3 field):
link-level speed factor at 03:00 (free flow) vs 17:00 (PM peak), class-weighted
line widths, DC--Baltimore inset on the peak panel.
-> paper/figures/trb/fig_congestion_map.{png,pdf} (+ panels copy)"""
import gzip, re, sys
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib import cm, colors as mcolors
sys.path.insert(0, "/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB/UrbanEV-Maryland/analysis")
import pubfig as pf

ROOT = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
OUT = ROOT/"paper/figures/trb"
plt.rcParams.update({"font.family":"serif"})

# ---- network geometry (major classes only) ----
rc = pd.read_parquet(ROOT/"Input/network/link_road_class.parquet")[["osm_highway"]]
KEEP = {"motorway":2.0,"trunk":1.5,"motorway_link":0.8,"trunk_link":0.6,
        "primary":1.0,"secondary":0.6,"tertiary":0.35}
cls = rc.osm_highway.to_dict()
nodes={}; segs={}; fs={}
for _,el in ET.iterparse(gzip.open(ROOT/"Input/network/maryland-network-pt2matsim.xml.gz","rt"),events=("end",)):
    if el.tag=="node": nodes[el.get("id")]=(float(el.get("x")),float(el.get("y")))
    elif el.tag=="link":
        lid=el.get("id")
        if cls.get(lid) in KEEP:
            a=nodes.get(el.get("from")); b=nodes.get(el.get("to"))
            if a and b: segs[lid]=(a,b); fs[lid]=float(el.get("freespeed"))
        el.clear()
print(f"[net] {len(segs):,} major links")

# ---- factors by hour from v3 change events (day 0) ----
fac = {3:{}, 17:{}}
cur=None; pend=[]
for ln in gzip.open(ROOT/"Input/network/networkChangeEvents_aadt_v3.xml.gz","rt"):
    if "networkChangeEvent " in ln:
        cur=int(re.search(r'startTime="(\d+):',ln).group(1)); pend=[]
    elif "refId" in ln and cur in (3,17):
        pend.append(re.search(r'refId="([^"]+)"',ln).group(1))
    elif "freespeed" in ln and cur in (3,17) and pend:
        v=float(re.search(r'value="([\d.]+)"',ln).group(1))
        for l in pend:
            if l in fs and fs[l]>0: fac[cur][l]=v/fs[l]
        pend=[]
    elif cur is not None and cur>17: break
print(f"[events] slowed links: 03h {len(fac[3]):,} | 17h {len(fac[17]):,}")

# counties
tr = gpd.read_file(ROOT/"pipeline/data/geo/tl_2020_24_tract.shp")[["GEOID","geometry"]]
tr["fips"]=tr.GEOID.str[:5]; cty=tr.dissolve("fips").to_crs(26985); state=cty.dissolve()
xmin,ymin,xmax,ymax = state.total_bounds

ids = list(segs.keys())
lines = [segs[l] for l in ids]
lw = np.array([KEEP[cls[l]] for l in ids])
f17 = np.array([fac[17].get(l,1.0) for l in ids])

# discrete congestion-severity classes (share of free-flow speed)
BINS = [0.0, 0.50, 0.70, 0.90, 0.97, 2.0]
COLS = ["#67000d", "#e31a1c", "#fd8d3c", "#fee08b", "#c9cfd6"]
LBL  = ["severe  (< 50% of free speed)", "heavy  (50–70%)", "moderate  (70–90%)",
        "light  (90–97%)", "free flow"]
kls = np.digitize(f17, BINS[1:-1])

fig, ax = plt.subplots(figsize=(14, 9))
cty.plot(ax=ax, color="#f7f8f9", edgecolor="#dde2e7", linewidth=0.5)
for k in [4, 3, 2, 1, 0]:                      # free-flow first, severe on top
    m = kls == k
    if not m.any(): continue
    idx = np.where(m)[0][np.argsort(lw[m])]
    wid = lw[idx]*0.55 if k == 4 else lw[idx]*2.0
    ax.add_collection(LineCollection([lines[i] for i in idx], colors=COLS[k],
                                     linewidths=wid, capstyle="round", zorder=3+(4-k)))
state.boundary.plot(ax=ax, color="#222", linewidth=1.1, zorder=9)
ax.set_xlim(xmin-4000,xmax+4000); ax.set_ylim(ymin-4000,ymax+4000)
ax.set_axis_off(); ax.set_aspect("equal")
ax.set_title("Network congestion at the PM peak (17:00) — MDOT AADT loading",
             fontsize=15, fontweight="bold", pad=10)
from matplotlib.lines import Line2D
handles=[Line2D([0],[0], color=c, lw=4.5, label=l) for c,l in zip(COLS,LBL)]
ax.legend(handles=handles, loc="lower left", fontsize=11.5, frameon=False,
          title="peak speed relative to free flow", title_fontsize=11.5)
fig.savefig(OUT/"fig_congestion_map.png", dpi=300, bbox_inches="tight")
fig.savefig(OUT/"fig_congestion_map.pdf", bbox_inches="tight")
plt.close(fig)
for e in [".png",".pdf"]:
    (ROOT/"paper/validation_package/panels"/("fig_congestion_map"+e)).write_bytes((OUT/("fig_congestion_map"+e)).read_bytes())
print("done -> severity-class map")
