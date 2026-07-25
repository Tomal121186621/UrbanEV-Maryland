#!/usr/bin/env python3
"""Diversion map: link-level EV VMT change, sw_T5r2 (corridor toll) vs sw_base_r2
(no-toll reference). Red = traffic lost (tolled corridors), blue = gained (diversion
routes). -> fig_diversion_map"""
import gzip, re, sys
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

ROOT = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
R = ROOT/"UrbanEV-Maryland/scenarios/maryland/output/runs_2026"
OUT = ROOT/"paper/figures/trb"
plt.rcParams.update({"font.family":"serif"})

rc = pd.read_parquet(ROOT/"Input/network/link_road_class.parquet")[["osm_highway"]]
KEEP = {"motorway","trunk","primary","secondary","tertiary","motorway_link","trunk_link","primary_link"}
cls = rc.osm_highway.to_dict()
nodes={}; segs={}; length={}
for _,el in ET.iterparse(gzip.open(ROOT/"Input/network/maryland-network-pt2matsim.xml.gz","rt"),events=("end",)):
    if el.tag=="node": nodes[el.get("id")]=(float(el.get("x")),float(el.get("y")))
    elif el.tag=="link":
        lid=el.get("id")
        if cls.get(lid) in KEEP:
            a=nodes.get(el.get("from")); b=nodes.get(el.get("to"))
            if a and b: segs[lid]=(a,b); length[lid]=float(el.get("length"))
        el.clear()
print(f"[net] {len(segs):,} links", flush=True)

rx=re.compile(r'type="left link".*link="([^"]+)"')
def counts(run):
    c={}
    for ln in gzip.open(R/run/"ITERS/it.50/50.events.xml.gz","rt"):
        if 'left link' in ln:
            m=rx.search(ln)
            if m:
                l=m.group(1)
                if l in segs: c[l]=c.get(l,0)+1
    return c
c0=counts("sw_base_r2"); print("[base] done", flush=True)
c1=counts("sw_T5r2");    print("[T5] done", flush=True)

ids=list(segs.keys())
dv=np.array([ (c1.get(l,0)-c0.get(l,0))*length[l]/1609.34 for l in ids])   # delta VMT (mi/3d, 25%)
tot_loss=dv[dv<0].sum(); tot_gain=dv[dv>0].sum()
print(f"delta VMT: loss {tot_loss:,.0f} gain {tot_gain:,.0f}")

tr=gpd.read_file(ROOT/"pipeline/data/geo/tl_2020_24_tract.shp")[["GEOID","geometry"]]
tr["fips"]=tr.GEOID.str[:5]; cty=tr.dissolve("fips").to_crs(26985); state=cty.dissolve()
xmin,ymin,xmax,ymax=state.total_bounds
lines=[segs[l] for l in ids]

fig,ax=plt.subplots(figsize=(13.5,9))
cty.plot(ax=ax,color="#f7f8f9",edgecolor="#dde2e7",linewidth=0.5)
ax.add_collection(LineCollection(lines,colors="#d3d9df",linewidths=0.35,zorder=2))
TH=30    # only draw meaningful changes (>30 mi over 3 days on a link)
loss=np.where(dv<-TH)[0]; gain=np.where(dv>TH)[0]
mag=np.abs(dv)
w=lambda idx: np.clip(mag[idx]/mag.max()*7,0.7,7)
ax.add_collection(LineCollection([lines[i] for i in gain],colors="#2166ac",
                                 linewidths=w(gain),capstyle="round",zorder=3))
ax.add_collection(LineCollection([lines[i] for i in loss],colors="#b2182b",
                                 linewidths=w(loss),capstyle="round",zorder=4))
state.boundary.plot(ax=ax,color="#222",linewidth=1.1,zorder=6)
ax.set_xlim(xmin-4000,xmax+4000); ax.set_ylim(ymin-4000,ymax+4000)
ax.set_axis_off(); ax.set_aspect("equal")
ax.set_title("EV traffic response to the corridor RUC (T5, 5.7¢/mi): change vs no-toll reference",
             fontsize=14, fontweight="bold", pad=10)
from matplotlib.lines import Line2D
ax.legend(handles=[Line2D([0],[0],color="#b2182b",lw=4,label="EV VMT lost (tolled corridors)"),
                   Line2D([0],[0],color="#2166ac",lw=4,label="EV VMT gained (diversion routes)")],
          loc="lower left", fontsize=11, frameon=False)
fig.savefig(OUT/"fig_diversion_map.png",dpi=300,bbox_inches="tight")
fig.savefig(OUT/"fig_diversion_map.pdf",bbox_inches="tight")
for e in [".png",".pdf"]:
    (ROOT/"paper/validation_package/panels"/("fig_diversion_map"+e)).write_bytes((OUT/("fig_diversion_map"+e)).read_bytes())
print("done -> fig_diversion_map")
