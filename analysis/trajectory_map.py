#!/usr/bin/env python3
"""Trip-trajectory map of public-charging EV users, differentiated by demographics — a
simulation-only spatial output. Reconstructs each sampled agent's daily activity trajectory
from the plans and draws it on the Maryland network, split by home-charger access (the
captivity axis) and shaded by income. Public (DC-fast) chargers overlaid.
NOTE: activity locations (hence routes) are fixed across pricing scenarios in this EV-only
simulation; what the surcharge changes is who keeps making public-charging trips (the captives).
-> paper/figures/trajectory_map.png"""
import sys, gzip, re, glob
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

REPO = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
RUNS = REPO / "UrbanEV-Maryland/scenarios/maryland/output/runs_2026"
rng = np.random.default_rng(7)

# ---- public-charging agents + demographics ----
f = sorted(glob.glob(str(RUNS / "baseline/ITERS/it.*/*charging_sessions.csv")),
           key=lambda p: int(p.split("it.")[1].split("/")[0]))[-1]
s = pd.read_csv(f, sep=";")
pub = s[s.charger_type_3way == "public"]
hc = pd.read_parquet(REPO / "paper/tables/per_agent_homecharger.parquet").set_index("person_id")
inc = pub.groupby("person_id").income_usd.first()
agents = pd.DataFrame({"income": inc})
agents["has_home"] = hc.reindex(agents.index)["has_home_charger"].fillna(True)
# stratified sample
cap = agents[~agents.has_home].sample(min(160, (~agents.has_home).sum()), random_state=1).index
noncap = agents[agents.has_home].sample(160, random_state=2).index
sample = set(cap) | set(noncap)
print(f"sampled {len(cap)} captive + {len(noncap)} home-charger public users")

# ---- trajectories from plans (activity coordinate sequence per sampled agent) ----
traj = {pid: [] for pid in sample}
pr = re.compile(r'<person id="([^"]+)"'); ar = re.compile(r'<activity type="[^"]*" x="([-\d.]+)" y="([-\d.]+)"')
cur = None
with gzip.open(REPO / "Input/population/plans_maryland_ev_2026.xml.gz", "rt") as fh:
    for ln in fh:
        mp = pr.search(ln)
        if mp:
            cur = mp.group(1) if mp.group(1) in sample else None
        elif cur:
            ma = ar.search(ln)
            if ma:
                traj[cur].append((float(ma.group(1)), float(ma.group(2))))
# keep distinct consecutive points (the places they travel between)
def clean(pts):
    out = []
    for p in pts:
        if not out or (abs(p[0]-out[-1][0])+abs(p[1]-out[-1][1])) > 50:
            out.append(p)
    return out
traj = {k: clean(v) for k, v in traj.items() if len(v) > 1}

# ---- Maryland counties + public chargers ----
tr = gpd.read_file(REPO / "pipeline/data/geo/tl_2020_24_tract.shp")[["GEOID", "geometry"]]
tr["fips"] = tr.GEOID.str[:5]
cty = tr.dissolve("fips").to_crs(26985)
state = cty.dissolve()
dx, dy = [], []
for el in ET.parse(REPO / "Input/chargers/chargers.xml").getroot():
    if el.get("type") in ("DCFC", "DCFC_TESLA"):
        dx.append(float(el.get("x"))); dy.append(float(el.get("y")))

fig, ax = plt.subplots(1, 2, figsize=(13.4, 6.4))
for a, (ids, title, col) in zip(ax, [(cap, "(a) No home charger  (captive)", pf.VERM),
                                     (noncap, "(b) Has home charger", pf.BLUE)]):
    cty.plot(ax=a, color="#f3f4f6", edgecolor="white", linewidth=0.6)
    state.boundary.plot(ax=a, color="#1a1a1a", linewidth=1.4)
    a.scatter(dx, dy, marker="^", s=10, color="#8a8f98", edgecolor="none", alpha=0.6, zorder=3)
    for pid in ids:
        t = traj.get(pid)
        if not t or len(t) < 2:
            continue
        xs, ys = zip(*t)
        a.plot(xs, ys, color=col, lw=0.6, alpha=0.35, zorder=4)
        a.plot(xs[0], ys[0], "o", color=col, ms=2.5, alpha=0.7, zorder=5)   # home
    a.set_axis_off(); a.set_aspect("equal"); a.set_title(title, fontsize=12)
leg = [Line2D([0], [0], color=pf.VERM, lw=2, label="captive user trajectory"),
       Line2D([0], [0], color=pf.BLUE, lw=2, label="home-charger user trajectory"),
       Line2D([0], [0], marker="^", color="none", markerfacecolor="#8a8f98", markersize=8, label="DC-fast charger"),
       Line2D([0], [0], marker="o", color="none", markerfacecolor="k", markersize=6, label="home location")]
fig.legend(handles=leg, loc="lower center", ncol=4, fontsize=9, frameon=False, bbox_to_anchor=(0.5, -0.01))
fig.suptitle("Daily trip trajectories of public-charging EV users, by home-charger access",
             fontsize=13, fontweight="bold", y=1.0)
fig.tight_layout(rect=(0, 0.04, 1, 0.98))
fig.savefig(REPO / "paper/figures/trajectory_map.png", dpi=300, bbox_inches="tight")
fig.savefig(REPO / "paper/figures/trajectory_map.pdf", bbox_inches="tight")
plt.close(fig)
print("-> trajectory_map.png")
print(f"  captive median income ${agents.loc[cap].income.median():,.0f} | "
      f"home-charger median ${agents.loc[noncap].income.median():,.0f}")
