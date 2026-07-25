#!/usr/bin/env python3
"""Full validation battery for the final gas-fallback + AADT-congested baseline (gasfb4)."""
import gzip, re, sys
import numpy as np, pandas as pd, sqlite3
ROOT="/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB"
R=f"{ROOT}/UrbanEV-Maryland/scenarios/maryland/output/runs_2026/gasfb4_baseline_25pct"
import glob
f=sorted(glob.glob(f"{R}/ITERS/it.*/[0-9]*.charging_sessions.csv"),key=lambda p:int(p.split('it.')[1].split('/')[0]))[-1]
it=int(f.split('it.')[1].split('/')[0])
d=pd.read_csv(f,sep=";")
print(f"=== gasfb4 VALIDATION (it.{it}) ===")
print("[1] charger shares (%):",d.charger_type.value_counts(normalize=True).mul(100).round(1).to_dict(),"| n",len(d))
p=d[d.charger_type.isin(["L2","DCFC","DCFC_TESLA"])]
print("[2] public %.1f%% | PHEV public %.0f%% (fleet 26%%)"%(len(p)/len(d)*100,(p.ev_type=='PHEV').mean()*100))
# occupancy shape vs ChargePoint
l2=d[d.charger_type=="L2"]; occ=np.zeros(24)
for a,b in l2[["time_start_s","time_end_s"]].values:
    for h in range(int(a//3600),int(min(b,a+86400)//3600)+1): occ[h%24]+=min(b,(h+1)*3600)-max(a,h*3600)
sim=occ/occ.sum()
con=sqlite3.connect(f"{ROOT}/Baseline Validation/Data/ChargePoint Data Collection/chargepoint_md.db")
q=pd.read_sql("SELECT strftime('%H',datetime(accessed_time_utc,'-4 hours')) h, SUM(in_use_ports)*1.0 u FROM charging_session_v2 GROUP BY h",con)
obs=(q.assign(h=q.h.astype(int)).sort_values("h").u/q.u.sum()).to_numpy()
print("[3] L2 occupancy shape r = %.3f (benchmark 0.83)"%np.corrcoef(sim,obs)[0,1])
h=(p.time_start_s//3600%24).astype(int).value_counts(normalize=True).sort_index().mul(100)
print("[4] public session-start peaks: 7h %.1f 8h %.1f | 17h %.1f"%(h.get(7,0),h.get(8,0),h.get(17,0)))
# energy-weighted overnight home share
hm=d[d.charger_type=="home"]; tot=night=0
for a,b,e in hm[["time_start_s","time_end_s","energy_kwh"]].values:
    if b<=a: continue
    tot+=e
    for h0 in range(int(a//3600),int(b//3600)+1):
        fr=(min(b,(h0+1)*3600)-max(a,h0*3600))/(b-a)
        if h0%24>=19 or h0%24<7: night+=e*fr
print("[5] home energy 19-07h: %.0f%% (Guidehouse 87%%)"%(night/tot*100))
print("[7] energy kWh: home %.1f L2 %.1f DCFC %.1f | agents charging %s"%(
  hm.energy_kwh.mean(),l2.energy_kwh.mean(),d[d.charger_type=='DCFC'].energy_kwh.mean() if (d.charger_type=='DCFC').any() else 0,f"{d.person_id.nunique():,}"))
# emergent UF from events
ev=sorted(glob.glob(f"{R}/ITERS/it.*/[0-9]*.events.xml.gz"),key=lambda p:int(p.split('it.')[1].split('/')[0]))[-1]
ptypes=set(pd.read_csv(f"{ROOT}/research/phev_gas_fallback_costs.csv").ev_type)
allph=set()
for ln in open(f"{ROOT}/UrbanEV-Maryland/scenarios/maryland/sample_25pct/electric_vehicles_25pct_phev.xml"):
    m=re.search(r'id="([^"]+)".*vehicle_type="([^"]+)"',ln)
    if m and m.group(2) in ptypes: allph.add(m.group(1))
rx=re.compile(r'person="([^"]+)".*energyChargedKWh="([\d.]+)"'); defic={}
for ln in gzip.open(ev,"rt"):
    if "gas_fallback" in ln:
        m=rx.search(ln)
        if m and m.group(1) in allph: defic[m.group(1)]=defic.get(m.group(1),0)+float(m.group(2))
ch=d[d.person_id.isin(allph)].groupby("person_id").energy_kwh.sum()
uf=np.array([ch.get(x,0)/(ch.get(x,0)+defic.get(x,0)) for x in allph if ch.get(x,0)+defic.get(x,0)>0.5])
print("[6] EMERGENT PHEV utility factor: mean %.2f median %.2f | never %.0f%% >0.8 %.0f%% (obs 0.3-0.6)"%(
  uf.mean(),np.median(uf),(uf<0.05).mean()*100,(uf>0.8).mean()*100))
print("DONE")
