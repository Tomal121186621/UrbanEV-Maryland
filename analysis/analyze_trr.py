#!/usr/bin/env python3
"""TRR closing analysis: (A) seed-replicate spread (mean, CV) for headline metrics;
(B) +/-25% public-price sensitivity of the public base and surcharge ceiling."""
import gzip, re
import numpy as np, pandas as pd, sqlite3
ROOT="/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB"
TRR=f"{ROOT}/UrbanEV-Maryland/scenarios/maryland/output/runs_trr"
S,D=4,3; PUB=["L2","DCFC","DCFC_TESLA"]

con=sqlite3.connect(f"{ROOT}/Baseline Validation/Data/ChargePoint Data Collection/chargepoint_md.db")
q=pd.read_sql("SELECT strftime('%H',datetime(accessed_time_utc,'-4 hours')) h, SUM(in_use_ports)*1.0 u FROM charging_session_v2 GROUP BY h",con)
OBS=(q.assign(h=q.h.astype(int)).sort_values("h").u/q.u.sum()).to_numpy()

def sess(run):
    return pd.read_csv(f"{run}/ITERS/it.50/50.charging_sessions.csv",sep=";")
def occ_r(d):
    l2=d[d.charger_type=="L2"]; occ=np.zeros(24)
    for a,b in l2[["time_start_s","time_end_s"]].values:
        for h in range(int(a//3600),int(min(b,a+86400)//3600)+1):
            occ[h%24]+=min(b,(h+1)*3600)-max(a,h*3600)
    return np.corrcoef(occ/occ.sum(),OBS)[0,1]
def toll_sum(run):
    t=0.0; rx=re.compile(r'amount="(-?[\d.eE+-]+)"')
    for ln in gzip.open(f"{run}/ITERS/it.50/50.events.xml.gz","rt"):
        if 'personMoney' in ln:
            m=rx.search(ln)
            if m: t+=abs(float(m.group(1)))
    return t

print("=== (A) SEED REPLICATES ===", flush=True)
rows={}
for seed in [1001,2002,3003]:
    b=sess(f"{TRR}/uq/seed{seed}_base_50")
    t1=sess(f"{TRR}/uq/seed{seed}_T1_50")
    e=b.groupby("charger_type").energy_kwh.sum()
    tot=e.sum()
    pubsh=e.reindex(PUB).fillna(0).sum()/tot*100
    homesh=e.get("home",0)/tot*100
    r=occ_r(b)
    rev1=t1[t1.charger_type.isin(PUB)].energy_kwh.sum()*S/D*365*0.05/1e6
    toll=toll_sum(f"{TRR}/uq/seed{seed}_T5_50")*S/D*365/1e6
    rows[seed]=dict(home_energy_pct=homesh,public_energy_pct=pubsh,occupancy_r=r,
                    T1_rev_M=rev1,T5_rev_M=toll)
    print(f"seed {seed}: {rows[seed]}", flush=True)
df=pd.DataFrame(rows).T
print("\nmean / CV(%) across seeds:")
for c in df.columns:
    m,s=df[c].mean(),df[c].std(ddof=1)
    print(f"  {c:18s} {m:8.2f}  CV {s/m*100:4.1f}%")

print("\n=== (B) PRICE SENSITIVITY (+/-25% public prices) ===", flush=True)
b0=sess(f"{ROOT}/UrbanEV-Maryland/scenarios/maryland/output/runs_2026/gasfb4_baseline_25pct")
p0=b0[b0.charger_type.isin(PUB)].energy_kwh.sum()
for tag in ["hi","lo"]:
    d=sess(f"{TRR}/sensitivity/sens_publicCh_{tag}_50")
    p=d[d.charger_type.isin(PUB)].energy_kwh.sum()
    e=d.groupby("charger_type").energy_kwh.sum(); tot=e.sum()
    ceiling=9.2*(p/p0)   # ceiling scales ~with base (documented approximation)
    print(f"{tag}: public kWh {p/p0-1:+.1%} vs central | public {e.reindex(PUB).fillna(0).sum()/tot*100:.1f}% of energy | implied +200c ceiling ~${ceiling:.1f}M ({ceiling/33.3*100:.0f}% of R*)")
print("DONE")
