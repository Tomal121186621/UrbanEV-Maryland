#!/usr/bin/env python3
"""Regenerate the 4 baseline-behavior thesis figures from the FINAL gasfb4 baseline
(gas fallback + AADT congestion + corrected prices). 25% sample scaled x4 where absolute.
-> /home/tomal/Documents/TRB Paper Thesis/figures/
   charger_composition, taxable_base, val_tier4_charging, validation_scorecard"""
import sys, sqlite3, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, "/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB/UrbanEV-Maryland/analysis")
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
OUT = Path("/home/tomal/Documents/TRB Paper Thesis/figures")
R = ROOT/"UrbanEV-Maryland/scenarios/maryland/output/runs_2026/gasfb4_baseline_25pct"
SCALE = 4  # 25% sample -> fleet

d = pd.read_csv(R/"ITERS/it.50/50.charging_sessions.csv", sep=";")
TYPES = ["home","work","L2","DCFC","DCFC_TESLA"]
LBL = {"home":"Home","work":"Work","L2":"Public L2","DCFC":"DCFC","DCFC_TESLA":"Tesla SC"}
col = {"home":pf.BLUE,"work":pf.GREEN,"L2":pf.ORANGE,"DCFC":pf.VERM,"DCFC_TESLA":pf.PURPLE}

# ---------- 1. charger_composition: sessions vs energy ----------
ss = d.charger_type.value_counts(normalize=True).reindex(TYPES).fillna(0)*100
ee = d.groupby("charger_type").energy_kwh.sum().reindex(TYPES).fillna(0)
ee = ee/ee.sum()*100
fig, ax = pf.newfig(7.2, 4.2)
x = np.arange(len(TYPES)); w=0.38
ax.bar(x-w/2, ss.values, w, label="sessions", color=[col[t] for t in TYPES], edgecolor="k", lw=0.4)
ax.bar(x+w/2, ee.values, w, label="energy", color=[col[t] for t in TYPES], edgecolor="k", lw=0.4, alpha=0.55, hatch="//")
for i,(a,b) in enumerate(zip(ss.values, ee.values)):
    ax.text(i-w/2, a+1, f"{a:.0f}", ha="center", fontsize=8)
    ax.text(i+w/2, b+1, f"{b:.0f}", ha="center", fontsize=8)
ax.set_xticks(x); ax.set_xticklabels([LBL[t] for t in TYPES], fontsize=9)
ax.set_ylabel("share (%)")
ax.set_title("Where EVs charge: sessions (solid) vs energy (hatched)")
from matplotlib.patches import Patch
ax.legend(handles=[Patch(fc="grey", ec="k", label="sessions"),
                   Patch(fc="grey", ec="k", alpha=0.55, hatch="//", label="energy")], fontsize=9)
pf.save(fig, OUT, "charger_composition")

# ---------- 2. taxable_base: energy base for surcharge instruments ----------
ann = d.groupby("charger_type").energy_kwh.sum().reindex(TYPES).fillna(0)*SCALE/3*365/1e6  # GWh/yr
fig, ax = pf.newfig(7.0, 4.2)
b = ax.bar(range(len(TYPES)), ann.values, 0.6, color=[col[t] for t in TYPES], edgecolor="k", lw=0.5)
for i,v in enumerate(ann.values):
    ax.text(i, v+ann.max()*0.02, f"{v:.0f}", ha="center", fontsize=9, fontweight="bold")
ax.set_xticks(range(len(TYPES))); ax.set_xticklabels([LBL[t] for t in TYPES], fontsize=9)
ax.set_ylabel("charged energy (GWh / yr)")
pub = ann[["L2","DCFC","DCFC_TESLA"]].sum()
ax.set_title(f"The taxable base problem: public charging is {pub/ann.sum()*100:.0f}% of EV energy")
pf.save(fig, OUT, "taxable_base")

# ---------- 3. val_tier4_charging: occupancy + session starts vs ChargePoint ----------
l2 = d[d.charger_type=="L2"]
occ = np.zeros(24)
for a,bb in l2[["time_start_s","time_end_s"]].values:
    for h in range(int(a//3600), int(min(bb,a+86400)//3600)+1):
        occ[h%24] += min(bb,(h+1)*3600)-max(a,h*3600)
sim_occ = occ/occ.sum()
con = sqlite3.connect(ROOT/"Baseline Validation/Data/ChargePoint Data Collection/chargepoint_md.db")
q = pd.read_sql("SELECT strftime('%H',datetime(accessed_time_utc,'-4 hours')) h, SUM(in_use_ports)*1.0 u "
                "FROM charging_session_v2 GROUP BY h", con)
obs_occ = (q.assign(h=q.h.astype(int)).sort_values("h").u/q.u.sum()).to_numpy()
r_occ = np.corrcoef(sim_occ, obs_occ)[0,1]
# plug-in events (session starts) from port transitions
tr = pd.read_sql("SELECT station_id, accessed_time_utc, in_use_ports FROM charging_session_v2 "
                 "ORDER BY station_id, accessed_time_utc", con)
tr["d"] = tr.groupby("station_id").in_use_ports.diff()
st = tr[tr.d>0]
sh = pd.to_datetime(st.accessed_time_utc, unit="s") - pd.Timedelta(hours=4)
obs_starts = sh.dt.hour.value_counts(normalize=True).sort_index().reindex(range(24)).fillna(0).to_numpy()
pubses = d[d.charger_type.isin(["L2","DCFC","DCFC_TESLA"])]
sim_starts = ((pubses.time_start_s//3600)%24).astype(int).value_counts(normalize=True).sort_index().reindex(range(24)).fillna(0).to_numpy()
r_st = np.corrcoef(sim_starts, obs_starts)[0,1]
fig, axs = plt.subplots(1, 2, figsize=(11, 3.9))
axs[0].plot(range(24), obs_occ*100, "-o", ms=3.5, color=pf.GREY, label="ChargePoint observed")
axs[0].plot(range(24), sim_occ*100, "-s", ms=3.5, color=pf.BLUE, label="simulated")
axs[0].set(title=f"(a) L2 occupancy by hour  (r = {r_occ:.2f})", xlabel="hour", ylabel="share of connected time (%)")
axs[1].plot(range(24), obs_starts*100, "-o", ms=3.5, color=pf.GREY, label="ChargePoint plug-ins")
axs[1].plot(range(24), sim_starts*100, "-s", ms=3.5, color=pf.ORANGE, label="simulated starts")
axs[1].set(title=f"(b) public session starts by hour  (r = {r_st:.2f})", xlabel="hour", ylabel="share of starts (%)")
for a in axs: a.grid(alpha=0.25); a.legend(fontsize=8)
fig.suptitle("Tier-4 validation: charging behavior vs observed ChargePoint panel (1.76M polls, 455 stations)",
             fontsize=12, fontweight="bold")
fig.tight_layout(rect=(0,0,1,0.93))
fig.savefig(OUT/"val_tier4_charging.png", dpi=300); plt.close(fig)
print(f"[tier4] occupancy r={r_occ:.3f} starts r={r_st:.3f}")

# ---------- 4. validation_scorecard ----------
rows = [
 ("Population marginals (held-out survey)",  "TVD",              "0.045", "< 0.10"),
 ("Population marginals (ACS 2020-24)",      "TVD",              "0.070", "< 0.10"),
 ("Joint associations (Cramer's V error)",   "mean abs err",     "0.057", "< 0.10"),
 ("Trip distances vs NHTS 2017 MD",          "quartiles (mi)",   "1.9/5.0/11.8 vs 1.9/4.6/11.6", "match"),
 ("EV fleet vs MVA registrations",           "county corr",      "> 0.99", "> 0.95"),
 ("Charging: home share of energy",          "share",            f"{ee['home']:.0f}%", "~80% (DOE)"),
 ("ChargePoint L2 occupancy shape",          "Pearson r",        "0.78 ± 0.01 (4 seeds)", "> 0.7"),
 ("Public session-start profile",            "Pearson r",        "0.93 (24h) / 0.84 daytime", "> 0.7"),
 ("Charging incidence per day",              "% of EVs",         "~18-25%", "18-20% (ATEAM)"),
 ("PHEV utility factor (emergent)",          "energy-weighted",  "0.50-0.59", "0.3-0.6 obs / 0.58 rated"),
 ("Peak congestion on loaded links",         "realized speed",   "11 mph peak / 43 mph night", "AADT-imposed"),
]
fig, ax = plt.subplots(figsize=(10.5, 0.42*len(rows)+1.2))
ax.axis("off")
tbl = ax.table(cellText=[[a,b,c,dd] for a,b,c,dd in rows],
               colLabels=["Validation check","Metric","Result","Benchmark"],
               loc="center", cellLoc="left", colWidths=[0.42,0.16,0.24,0.18])
tbl.auto_set_font_size(False); tbl.set_fontsize(9); tbl.scale(1, 1.35)
for j in range(4):
    tbl[0,j].set_facecolor("#2C6DA3"); tbl[0,j].set_text_props(color="white", fontweight="bold")
ax.set_title("Validation scorecard — final baseline (gas-fallback model, AADT-congested network)",
             fontsize=12, fontweight="bold", pad=18)
fig.tight_layout()
fig.savefig(OUT/"validation_scorecard.png", dpi=300, bbox_inches="tight"); plt.close(fig)
print("[scorecard] done")
print("ALL FIGURES REGENERATED ->", OUT)
