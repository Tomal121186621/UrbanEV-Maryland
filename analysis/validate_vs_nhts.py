#!/usr/bin/env python3
"""INDEPENDENT trip/VMT validation vs NHTS 2022 (NextGen, ORNL) — a national travel survey
never used anywhere in our pipeline (training data = MWCOG RTS 2017-18). Honest scope:
NHTS filtered to CENSUS DIVISION 5 (South Atlantic, incl. MD) URBAN, private-vehicle trips,
trip weights applied. Our side = trip distances extracted from the ACTUAL simulation plans
(model output, not training data) for a random sample of EV agents.
  -> paper/figures/validation_trb/fig_val_nhts.png  + printed stats"""
import sys, gzip, re, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

REPO = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
OUT = REPO/"paper/figures/validation_trb"
NHTS = REPO/"pipeline/data/reference/nhts2022/tripv2pub.csv"
PLANS = REPO/"Input/population/plans_maryland_ev_2026.xml.gz"
DETOUR = 1.25                                   # network detour factor used at plan build

# ---- NHTS 2017 MARYLAND state add-on (HHSTATE='MD'; state-representative with the MD
# add-on sample, per FHWA; NHTS 2022 dropped HHSTATE entirely so it cannot be used
# state-specifically) — private-vehicle trips, trip weights applied ----
nh = pd.read_parquet(REPO/"pipeline/data/reference/nhts2017/md_car_trips.parquet")
print(f"NHTS 2017 Maryland: {len(nh):,} private-vehicle trips (weighted)")

# ---- our model output: trip distances from simulation plans (sampled agents) ----
rng = np.random.default_rng(11)
pr = re.compile(r'<person id="([^"]+)"'); ar = re.compile(r'<activity type="[^"]*" x="([-\d.]+)" y="([-\d.]+)"')
dists = []; day_vmt = {}; cur=None; pts=[]; keep=False; n_agents=0
with gzip.open(PLANS, "rt") as fh:
    for ln in fh:
        mp = pr.search(ln)
        if mp:
            if keep and len(pts) > 1:
                xs = np.array(pts)
                d = np.sqrt(((xs[1:]-xs[:-1])**2).sum(1))/1609.34*DETOUR   # m -> mi; euclid*detour recovers trip distance
                d = d[(d>0.05)&(d<200)]
                dists.extend(d.tolist()); day_vmt[cur] = d.sum()/3         # 72h plan -> per day
            cur = mp.group(1); keep = rng.random() < 0.15; pts=[]; n_agents += keep
        elif keep:
            ma = ar.search(ln)
            if ma: pts.append((float(ma.group(1)), float(ma.group(2))))
if keep and len(pts) > 1:
    xs=np.array(pts); d=np.sqrt(((xs[1:]-xs[:-1])**2).sum(1))/1609.34*DETOUR
    d=d[(d>0.05)&(d<200)]; dists.extend(d.tolist()); day_vmt[cur]=d.sum()/3
sim_d = np.array(dists); sim_vmt = np.array(list(day_vmt.values()))
print(f"sim plans: {n_agents:,} sampled agents, {len(sim_d):,} trips")

def wq(v, w, qs):   # weighted quantiles
    o=np.argsort(v); v,w=np.asarray(v)[o],np.asarray(w)[o]
    cw=np.cumsum(w)/np.sum(w); return [float(v[np.searchsorted(cw,q)]) for q in qs]

fig, ax = plt.subplots(1, 2, figsize=(11, 4.0))
# (a) trip distance distributions — no clipping: filter to <=60 mi and annotate excluded share
bins=np.linspace(0,60,41)
nh60 = nh[nh.TRPMILES<=60]; sd60 = sim_d[sim_d<=60]
excl_n = 1 - nh60.WTTRDFIN.sum()/nh.WTTRDFIN.sum(); excl_s = 1 - len(sd60)/len(sim_d)
ax[0].hist(nh60.TRPMILES, bins=bins, weights=nh60.WTTRDFIN, density=True,
           alpha=0.55, color=pf.BLUE, label=f"NHTS 2017 Maryland (n={len(nh):,}, weighted)", edgecolor="white", lw=0.2)
ax[0].hist(sd60, bins=bins, density=True, alpha=0.55, color=pf.ORANGE,
           label=f"simulated EV trips (n={len(sim_d):,})", edgecolor="white", lw=0.2)
nm = wq(nh.TRPMILES.values, nh.WTTRDFIN.values, [0.5])[0]
ax[0].axvline(nm, color=pf.BLUE, ls="--", lw=1); ax[0].axvline(np.median(sim_d), color=pf.ORANGE, ls="--", lw=1)
ax[0].text(0.98, 0.45, f"trips >60 mi not shown:\nNHTS {excl_n*100:.1f}%, sim {excl_s*100:.1f}%",
           transform=ax[0].transAxes, fontsize=7.5, ha="right", style="italic", color=pf.GREY)
ax[0].set(xlabel="trip distance (mi)", ylabel="density", title="(a) Trip distance distribution")
ax[0].legend(fontsize=8); ax[0].grid(alpha=0.2)
# (b) daily VMT per driver — no clipping; odometer references as legend entries
v120 = sim_vmt[sim_vmt<=120]; excl_v = 1 - len(v120)/len(sim_vmt)
ax[1].hist(v120, bins=40, range=(0,120), density=True, color=pf.ORANGE, alpha=0.7,
           edgecolor="white", lw=0.2, label=f"simulated daily VMT (mean {sim_vmt.mean():.1f} mi)")
ax[1].axvspan(7165/348, 10587/348, color=pf.GREY, alpha=0.25, label="GWU odometer range (20.6–30.4)")
ax[1].axvline(12100/348, color=pf.GREEN, ls="--", lw=1.6, label="Argonne odometer (34.8)")
ax[1].set(xlabel="daily VMT per EV (mi)", ylabel="density", title="(b) Daily VMT vs real-EV odometer studies")
ax[1].legend(fontsize=8, loc="upper right"); ax[1].grid(alpha=0.2)
fig.suptitle("Independent travel validation: NHTS 2017 Maryland (never used in training) + odometer studies",
             fontsize=12, fontweight="bold", y=1.02)
fig.tight_layout(rect=(0,0,1,0.97))
fig.savefig(OUT/"fig_val_nhts.png", dpi=300); fig.savefig(OUT/"fig_val_nhts.pdf")
plt.close(fig)
qs=[0.25,0.5,0.75]
print(f"\ntrip distance quartiles: NHTS {wq(nh.TRPMILES.values,nh.WTTRDFIN.values,qs)} vs sim {np.quantile(sim_d,qs).round(1).tolist()}")
print(f"daily VMT: sim mean {sim_vmt.mean():.1f} | odometer range 20.6-34.8 mi/day")
print("-> fig_val_nhts.png")
