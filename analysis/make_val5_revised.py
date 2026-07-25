#!/usr/bin/env python3
"""REVISED UrbanEV validation figures from the FINAL gasfb4 baseline -> validation_package/panels:
   val5_urbanev_charging  : 4-panel (occupancy | session starts | venue shares | emergent UF)
   fig_val_session_starts : standalone session-start validation
"""
import sys, re, sqlite3
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, "/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB/UrbanEV-Maryland/analysis")
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
OUT = ROOT/"paper/validation_package/panels"
R = ROOT/"UrbanEV-Maryland/scenarios/maryland/output/runs_2026/gasfb4_baseline_25pct"
d = pd.read_csv(R/"ITERS/it.50/50.charging_sessions.csv", sep=";")
con = sqlite3.connect(ROOT/"Baseline Validation/Data/ChargePoint Data Collection/chargepoint_md.db")

# --- occupancy ---
l2 = d[d.charger_type=="L2"]; occ = np.zeros(24)
for a,b in l2[["time_start_s","time_end_s"]].values:
    for h in range(int(a//3600), int(min(b,a+86400)//3600)+1):
        occ[h%24] += min(b,(h+1)*3600)-max(a,h*3600)
sim_occ = occ/occ.sum()
q = pd.read_sql("SELECT strftime('%H',datetime(accessed_time_utc,'-4 hours')) h, SUM(in_use_ports)*1.0 u FROM charging_session_v2 GROUP BY h", con)
obs_occ = (q.assign(h=q.h.astype(int)).sort_values("h").u/q.u.sum()).to_numpy()
r_occ = np.corrcoef(sim_occ, obs_occ)[0,1]
# --- session starts ---
tr = pd.read_sql("SELECT station_id, accessed_time_utc, in_use_ports FROM charging_session_v2 ORDER BY station_id, accessed_time_utc", con)
tr["dd"] = tr.groupby("station_id").in_use_ports.diff()
sh = pd.to_datetime(tr[tr.dd>0].accessed_time_utc, unit="s") - pd.Timedelta(hours=4)
sh = sh[sh.dt.weekday < 5]   # weekday plug-ins (simulated day is a weekday)
obs_st = sh.dt.hour.value_counts(normalize=True).sort_index().reindex(range(24)).fillna(0).to_numpy()
pub = d[d.charger_type.isin(["L2","DCFC","DCFC_TESLA"])]
sim_st = ((pub.time_start_s//3600)%24).astype(int).value_counts(normalize=True).sort_index().reindex(range(24)).fillna(0).to_numpy()
r_st = np.corrcoef(sim_st, obs_st)[0,1]
_m = (np.arange(24)>=6)&(np.arange(24)<=22)
r_day = np.corrcoef(sim_st[_m]/sim_st[_m].sum(), obs_st[_m]/obs_st[_m].sum())[0,1]
# --- emergent UF ---
ptypes = set(pd.read_csv(ROOT/"research/phev_gas_fallback_costs.csv").ev_type)
phev = set()
for ln in open(ROOT/"UrbanEV-Maryland/scenarios/maryland/sample_25pct/electric_vehicles_25pct_phev.xml"):
    m = re.search(r'id="([^"]+)".*vehicle_type="([^"]+)"', ln)
    if m and m.group(2) in ptypes: phev.add(m.group(1))
rx = re.compile(r'person="([^"]+)".*energyChargedKWh="([\d.]+)"'); defic = {}
for ln in open("/tmp/gasfb4_it50_fallback.txt"):
    m = rx.search(ln)
    if m and m.group(1) in phev: defic[m.group(1)] = defic.get(m.group(1),0)+float(m.group(2))
ch = d[d.person_id.isin(phev)].groupby("person_id").energy_kwh.sum()
uf = np.array([ch.get(p,0)/(ch.get(p,0)+defic.get(p,0)) for p in phev if ch.get(p,0)+defic.get(p,0)>0.5])
C, G = ch.sum(), sum(defic.values())

TYPES = ["home","work","L2","DCFC","DCFC_TESLA"]
LBL = ["Home","Work","Public\nL2","DCFC","Tesla\nSC"]
ee = d.groupby("charger_type").energy_kwh.sum().reindex(TYPES).fillna(0); ee = ee/ee.sum()*100
ss = d.charger_type.value_counts(normalize=True).reindex(TYPES).fillna(0)*100

fig, axs = plt.subplots(2, 2, figsize=(11.5, 8))
a = axs[0,0]
a.plot(range(24), obs_occ*100, "-o", ms=3.5, color=pf.GREY, label="ChargePoint observed")
a.plot(range(24), sim_occ*100, "-s", ms=3.5, color=pf.BLUE, label="simulated")
a.set(title=f"(a) Public L2 occupancy by hour (r = {r_occ:.2f})", xlabel="hour of day", ylabel="share of connected time (%)")
a.legend(fontsize=8)
a = axs[0,1]
a.plot(range(24), obs_st*100, "-o", ms=3.5, color=pf.GREY, label="ChargePoint plug-in events")
a.plot(range(24), sim_st*100, "-s", ms=3.5, color=pf.ORANGE, label="simulated public starts")
a.set(title=f"(b) Public session starts by hour (r = {r_st:.2f}; daytime-only {r_day:.2f})", xlabel="hour of day", ylabel="share of starts (%)")
a.legend(fontsize=8)
a = axs[1,0]
x = np.arange(len(TYPES)); w = 0.38
a.bar(x-w/2, ss.values, w, color=pf.BLUE, edgecolor="k", lw=0.4, label="sessions")
a.bar(x+w/2, ee.values, w, color=pf.ORANGE, edgecolor="k", lw=0.4, label="energy")
a.set_xticks(x); a.set_xticklabels(LBL, fontsize=8.5)
a.axhline(80, color=pf.GREY, ls="--", lw=1); a.text(3.1, 81.5, "DOE ~80% home (energy)", fontsize=7.5, color=pf.GREY)
a.set(title="(c) Charging venue shares", ylabel="share (%)"); a.legend(fontsize=8)
a = axs[1,1]
a.hist(uf, bins=24, color=pf.GREEN, edgecolor="k", lw=0.4)
a.axvspan(0.3, 0.6, color=pf.GREY, alpha=0.18)
a.axvline(0.58, color=pf.VERM, ls="--", lw=1.4)
a.text(0.585, a.get_ylim()[1]*0.9 if a.get_ylim()[1]>0 else 1, " EPA rated 0.58", fontsize=8, color=pf.VERM)
a.set(title=f"(d) Emergent PHEV utility factor (fleet {C/(C+G):.2f}–{(C+87626)/(C+87626+G):.2f}; shaded = observed range)",
      xlabel="electric share of PHEV energy", ylabel="PHEVs")
for ax in axs.flat: ax.grid(alpha=0.25)
fig.suptitle("UrbanEV charging validation — final baseline (PHEV gas fallback, AADT-congested network)",
             fontsize=13, fontweight="bold")
fig.tight_layout(rect=(0,0,1,0.95))
fig.savefig(OUT/"val5_urbanev_charging.png", dpi=300); fig.savefig(OUT/"val5_urbanev_charging.pdf")
plt.close(fig)

fig, ax = pf.newfig(7.4, 4.4)
ax.plot(range(24), obs_st*100, "-o", ms=4, color=pf.GREY, label="ChargePoint weekday plug-in events")
ax.plot(range(24), sim_st*100, "-s", ms=4, color=pf.ORANGE, label="simulated public session starts")
ax.set(xlabel="hour of day", ylabel="share of session starts (%)")
ax.set_title(f"Public session starts: simulated vs observed weekday plug-ins (r = {r_st:.2f}; daytime-only {r_day:.2f})")
ax.legend(fontsize=9)
pf.save(fig, OUT, "fig_val_session_starts")
print(f"done: occupancy r={r_occ:.3f}, starts r={r_st:.3f}, UF n={len(uf)}")
