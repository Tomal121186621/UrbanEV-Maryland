#!/usr/bin/env python3
"""Uniform trip-validation panel (replaces stitched val2) — regenerated FROM DATA in the same
style as the other validation panels. Survey = MWCOG RTS auto-driver trips (weighted).
Model side = trips extracted from the ACTUAL simulation plans (EV agents' car trips).
Panels: (a) trip distance, (b) departure hour, (c) daily VMT. TVD in titles. No external
reference lines. -> paper/figures/validation_trb/val2_trips.png (+pdf)"""
import sys, gzip, re, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

REPO = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
OUT = REPO/"paper/figures/validation_trb"
PLANS = REPO/"Input/population/plans_maryland_ev_2026.xml.gz"
DETOUR = 1.25
SURVEY, SYNTH = pf.BLUE, pf.ORANGE

# ---- survey: auto-driver trips, weighted ----
st = pd.read_parquet(REPO/"pipeline/data/interim/survey_trip.parquet")
sv = st[(st.travel_mode == 4) & (st.distance > 0) & (st.distance < 200)].copy()
sv["dep_h"] = (sv.dep_min // 60).clip(0, 23)
sv_day = sv.groupby(["person_id"]).agg(vmt=("distance","sum"), w=("wttrdfin","first"))  # person-day VMT

# ---- sim plans: distances, departure hours, daily VMT (sampled agents) ----
rng = np.random.default_rng(11)
pr = re.compile(r'<person id="([^"]+)"')
ar = re.compile(r'<activity type="[^"]*" x="([-\d.]+)" y="([-\d.]+)"(?:[^>]*end_time="(\d+):(\d+):\d+")?')
dists, deps, day_vmt = [], [], {}
cur=None; pts=[]; keep=False; n_agents=0
with gzip.open(PLANS, "rt") as fh:
    for ln in fh:
        mp = pr.search(ln)
        if mp:
            if keep and len(pts) > 1:
                xs = np.array([(p[0],p[1]) for p in pts])
                d = np.sqrt(((xs[1:]-xs[:-1])**2).sum(1))/1609.34*DETOUR
                m = (d>0.05)&(d<200)
                dists.extend(d[m].tolist()); day_vmt[cur] = d[m].sum()/3
                deps.extend([p[2] for p in pts[:-1] if p[2] is not None])
            cur = mp.group(1); keep = rng.random() < 0.15; pts=[]; n_agents += keep
        elif keep:
            ma = ar.search(ln)
            if ma:
                hh = int(ma.group(3)) % 24 if ma.group(3) else None
                pts.append((float(ma.group(1)), float(ma.group(2)), hh))
sim_d = np.array(dists); sim_dep = np.array(deps); sim_vmt = np.array(list(day_vmt.values()))
print(f"survey auto-drv trips {len(sv):,} | sim: {n_agents:,} agents, {len(sim_d):,} trips, {len(sim_dep):,} departures")

def tvd_binned(a, wa, b, edges):
    ha,_ = np.histogram(a, edges, weights=wa); hb,_ = np.histogram(b, edges)
    ha = ha/ha.sum(); hb = hb/hb.sum()
    return 0.5*np.abs(ha-hb).sum()

fig, ax = plt.subplots(1, 3, figsize=(12.6, 3.8))
# (a) trip distance
e = np.linspace(0, 60, 41)
sv60 = sv[sv.distance<=60]; sd60 = sim_d[sim_d<=60]
t1 = tvd_binned(sv.distance.clip(0,60), sv.wttrdfin, np.clip(sim_d,0,60), e)
ax[0].hist(sv60.distance, bins=e, weights=sv60.wttrdfin, density=True, alpha=0.55, color=SURVEY,
           label="survey (weighted)", edgecolor="white", lw=0.2)
ax[0].hist(sd60, bins=e, density=True, alpha=0.55, color=SYNTH, label="simulated plans", edgecolor="white", lw=0.2)
ax[0].set(xlabel="trip distance (mi)", ylabel="density", title=f"(a) Trip distance  (TVD={t1:.3f})")
# (b) departure hour
e2 = np.arange(0, 25)
t2 = tvd_binned(sv.dep_h, sv.wttrdfin, sim_dep, e2)
ax[1].hist(sv.dep_h, bins=e2, weights=sv.wttrdfin, density=True, alpha=0.55, color=SURVEY,
           label="survey (weighted)", edgecolor="white", lw=0.2)
ax[1].hist(sim_dep, bins=e2, density=True, alpha=0.55, color=SYNTH, label="simulated plans", edgecolor="white", lw=0.2)
ax[1].set(xlabel="departure hour", ylabel="density", title=f"(b) Departure hour  (TVD={t2:.3f})", xticks=range(0,25,4))
# (c) daily VMT — filter (no clip-pileup), annotate excluded shares
e3 = np.linspace(0, 120, 41)
svd = sv_day[sv_day.vmt<=120]; smv = sim_vmt[sim_vmt<=120]
exs = 1 - svd.w.sum()/sv_day.w.sum(); exm = 1 - len(smv)/len(sim_vmt)
t3 = tvd_binned(sv_day.vmt.clip(0,120), sv_day.w, np.clip(sim_vmt,0,120), e3)
ax[2].hist(svd.vmt, bins=e3, weights=svd.w, density=True, alpha=0.55, color=SURVEY,
           label="survey (weighted)", edgecolor="white", lw=0.2)
ax[2].hist(smv, bins=e3, density=True, alpha=0.55, color=SYNTH,
           label="simulated plans", edgecolor="white", lw=0.2)
ax[2].set(xlabel="daily VMT per driver (mi)", ylabel="density", title=f"(c) Daily VMT  (TVD={t3:.3f})")
for a in ax: a.legend(fontsize=8); a.grid(alpha=0.2)
fig.suptitle("Trip generation validation: simulated plans vs survey (weighted, auto-driver trips)",
             fontsize=12.5, fontweight="bold", y=1.02)
fig.tight_layout(rect=(0,0,1,0.97))
fig.savefig(OUT/"val2_trips.png", dpi=300); fig.savefig(OUT/"val2_trips.pdf")
plt.close(fig)
print(f"TVD: distance {t1:.3f} | departure {t2:.3f} | dailyVMT {t3:.3f}")
print("-> val2_trips.png")
