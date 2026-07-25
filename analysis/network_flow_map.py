#!/usr/bin/env python3
"""Full Maryland road-network diagram loaded with simulated EV traffic (a simulation-only
output): every network link drawn, colored and weighted by EV vehicle-miles. Plus a route-
analysis panel (VMT by road class, top corridors, per-agent interstate share, VMT concentration).
-> paper/figures/network_flow_map.png + route_analysis.png"""
import sys, gzip
from pathlib import Path
import numpy as np, pandas as pd
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
import geopandas as gpd
from matplotlib.collections import LineCollection
from matplotlib.colors import LogNorm

REPO = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
B = REPO / "UrbanEV-Maryland/scenarios/maryland/output/runs_2026/baseline"
NET = REPO / "Input/network/maryland-network-pt2matsim.xml.gz"
lv = pd.read_parquet(B / "route_analysis/link_vmt.parquet")
corr = pd.read_parquet(B / "route_analysis/link_corridor.parquet")

# ---- parse network geometry (nodes then links) ----
nodes = {}; seg = []; vmt = []; rc = []
vmap = lv.vmt.to_dict(); cmap = lv.road_class.to_dict()
for _, el in ET.iterparse(gzip.open(NET, "rt"), events=("end",)):
    if el.tag == "node":
        nodes[el.get("id")] = (float(el.get("x")), float(el.get("y")))
    elif el.tag == "link":
        a, b = nodes.get(el.get("from")), nodes.get(el.get("to"))
        if a and b:
            lid = el.get("id")
            seg.append((a, b)); vmt.append(vmap.get(lid, 0.0)); rc.append(cmap.get(lid, "local"))
        el.clear()
seg = np.array(seg); vmt = np.array(vmt); rc = np.array(rc)
print(f"network: {len(seg):,} links, total VMT {vmt.sum():,.0f} mi/day")

# ---- FIG 1: full-network flow diagram ----
tr = gpd.read_file(REPO / "pipeline/data/geo/tl_2020_24_tract.shp")[["GEOID", "geometry"]]
tr["fips"] = tr.GEOID.str[:5]
cty = tr.dissolve("fips").to_crs(26985); state = cty.dissolve()
fig, ax = plt.subplots(figsize=(13, 11))
cty.boundary.plot(ax=ax, color="#d8dce1", linewidth=0.6, zorder=1)
state.boundary.plot(ax=ax, color="#555555", linewidth=1.2, zorder=1)
order = np.argsort(vmt)                       # draw low-VMT first, high on top
s, v = seg[order], vmt[order]
vpos = np.clip(v, 1e-3, None)
lw = 0.05 + 2.6 * np.sqrt(v / v.max())        # width ~ sqrt(VMT)
lc = LineCollection(s, array=vpos, cmap="turbo", norm=LogNorm(vmin=max(1e-2, np.percentile(vpos[vpos > 0.01], 40)), vmax=v.max()),
                    linewidths=lw, capstyle="round")
ax.add_collection(lc)
ax.set_aspect("equal"); ax.autoscale(); ax.set_axis_off()
cb = fig.colorbar(lc, ax=ax, fraction=0.03, pad=0.01)
cb.set_label("EV vehicle-miles per link (per day, log scale)", fontsize=11)
ax.set_title("Simulated electric-vehicle traffic on the Maryland road network", fontsize=15, pad=8)
fig.savefig(REPO / "paper/figures/network_flow_map.png", dpi=250, bbox_inches="tight")
fig.savefig(REPO / "paper/figures/network_flow_map.pdf", bbox_inches="tight")
plt.close(fig); print("-> network_flow_map.png")

# ---- FIG 2: route analysis (4 panels) ----
fig, ax = plt.subplots(2, 2, figsize=(11, 8.4)); ax = ax.ravel()
RC = ["interstate", "arterial", "collector", "local"]
by_rc = pd.Series(vmt).groupby(pd.Series(rc)).sum().reindex(RC).fillna(0)
share = by_rc / by_rc.sum() * 100
ax[0].bar(range(4), share.values, color=[pf.VERM, pf.ORANGE, pf.GREEN, pf.GREY], edgecolor="k", lw=0.3)
ax[0].set_xticks(range(4)); ax[0].set_xticklabels([r.title() for r in RC])
for i, v_ in enumerate(share.values): ax[0].text(i, v_ + 1, f"{v_:.0f}%", ha="center", fontsize=9)
ax[0].set(ylabel="% of EV VMT", title="(a) EV VMT by road class")

# top corridors
byc = corr.join(lv["vmt"]).groupby("corridor").vmt.sum().sort_values(ascending=False).head(8)[::-1]
ax[1].barh(byc.index, byc.values / 1000, color=pf.BLUE, edgecolor="k", lw=0.3)
ax[1].set(xlabel="EV VMT (thousand mi/day)", title="(b) EV VMT by named corridor")

# per-agent interstate share of VMT
pa = pd.read_csv(B / "route_analysis" / ".." / "shadow_tax_gap_per_agent.csv") if (B / "shadow_tax_gap_per_agent.csv").exists() else None
try:
    rcv = pd.read_parquet(B / "route_analysis/link_vmt.parquet")
except Exception:
    rcv = None
# concentration curve: cumulative VMT vs cumulative links (few links carry most miles)
vs = np.sort(vmt)[::-1]
cum = np.cumsum(vs) / vs.sum()
frac_links = np.arange(1, len(vs) + 1) / len(vs)
ax[2].plot(frac_links * 100, cum * 100, color=pf.GREEN, lw=2)
ax[2].plot([0, 100], [0, 100], "k--", lw=0.8)
i10 = np.searchsorted(frac_links, 0.10)
ax[2].axvline(10, color=pf.GREY, ls=":", lw=0.8)
ax[2].annotate(f"top 10% of links\ncarry {cum[i10]*100:.0f}% of VMT", (10, cum[i10]*100),
               xytext=(25, 40), fontsize=9, arrowprops=dict(arrowstyle="->", lw=0.7))
ax[2].set(xlabel="% of links (busiest first)", ylabel="% of EV VMT", title="(c) VMT concentration on the network")

# interstate share histogram (link-level VMT weighted) -> distribution of link VMT by class (box)
data = [np.log10(np.clip(vmt[rc == r], 1e-2, None)) for r in RC]
ax[3].boxplot(data, tick_labels=[r.title() for r in RC], showfliers=False,
              patch_artist=True, boxprops=dict(facecolor=pf.BLUE, alpha=0.5))
ax[3].set(ylabel="log10 link VMT (mi/day)", title="(d) Per-link VMT by road class")
for a in ax: a.grid(alpha=0.2)
fig.tight_layout()
fig.savefig(REPO / "paper/figures/route_analysis.png", dpi=300, bbox_inches="tight")
fig.savefig(REPO / "paper/figures/route_analysis.pdf", bbox_inches="tight")
plt.close(fig); print("-> route_analysis.png")
print(f"  road-class VMT %: " + ", ".join(f"{r} {s:.0f}%" for r, s in share.items()))
print(f"  top 10% of links carry {cum[i10]*100:.0f}% of EV VMT")
