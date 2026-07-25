#!/usr/bin/env python3
"""Equal-yield incidence analysis: annual burden as % of household income by income
octile (hh_income_detailed 1-8), for each recovery instrument scaled to raise R*.
Per-agent bases: home kWh & public kWh (baseline sessions), VMT (plans, euclid x detour),
corridor-tolled miles (sw_T5r2 personMoney), flat fee (equal).
-> fig_incidence + printed Suits-style summary."""
import gzip, re, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, "/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB/UrbanEV-Maryland/analysis")
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
R = ROOT/"UrbanEV-Maryland/scenarios/maryland/output/runs_2026"
OUT = ROOT/"paper/figures/trb"
RSTAR = 33.3e6; DAYS = 3; DETOUR = 1.30
INCOME_MID = {1:7500.,2:20000.,3:30000.,4:42500.,5:62500.,6:87500.,7:125000.,8:200000.}

# --- per-agent charging bases + income octile (baseline it.50 sessions) ---
d = pd.read_csv(R/"gasfb4_baseline_25pct/ITERS/it.50/50.charging_sessions.csv", sep=";")
d["oct"] = pd.to_numeric(d.hh_income_detailed, errors="coerce")
home = d[d.charger_type=="home"].groupby("person_id").energy_kwh.sum()
pub  = d[d.charger_type.isin(["L2","DCFC","DCFC_TESLA"])].groupby("person_id").energy_kwh.sum()
octl = d.groupby("person_id")["oct"].first()

# --- per-agent VMT from the 25% plans (euclidean x detour, one day) ---
vmt = {}
pid=None; prev=None; tot=0.0
oct_pl={}
rx_p=re.compile(r'<person id="([^"]+)"'); rx_a=re.compile(r'<activity[^>]*x="([-\d.]+)" y="([-\d.]+)"')
rx_o=re.compile(r'name="hh_income_detailed"[^>]*>(\d+)<')
f=ROOT/"UrbanEV-Maryland/scenarios/maryland/sample_25pct/plans_25pct_phev.xml.gz"
for ln in gzip.open(f,"rt"):
    m=rx_p.search(ln)
    if m:
        if pid is not None: vmt[pid]=tot/DAYS*DETOUR/1609.34
        pid=m.group(1); prev=None; tot=0.0
        continue
    mo=rx_o.search(ln)
    if mo and pid is not None: oct_pl[pid]=int(mo.group(1))
    m=rx_a.search(ln)
    if m:
        xy=(float(m.group(1)),float(m.group(2)))
        if prev is not None: tot+=((xy[0]-prev[0])**2+(xy[1]-prev[1])**2)**0.5
        prev=xy
if pid is not None: vmt[pid]=tot/DAYS*DETOUR/1609.34
vmt=pd.Series(vmt)
print(f"[vmt] agents {len(vmt):,} mean {vmt.mean():.1f} mi/day")

# --- per-agent corridor toll payments (sw_T5r2 money events) ---
pay={}
rx=re.compile(r'type="personMoney".*person="([^"]+)".*amount="(-?[\d.eE+-]+)"')
for ln in gzip.open(R/"sw_T5r2/ITERS/it.50/50.events.xml.gz","rt"):
    if 'personMoney' in ln:
        m=rx.search(ln)
        if m: pay[m.group(1)]=pay.get(m.group(1),0)+abs(float(m.group(2)))
toll=pd.Series(pay)
print(f"[toll] payers {len(toll):,} total ${toll.sum():,.0f}/3d")

# --- assemble equal-yield burdens ---
agents = octl.index.union(vmt.index)
A = pd.DataFrame(index=agents)
A["oct"] = pd.Series(oct_pl).reindex(agents)
A["oct"] = A["oct"].fillna(octl.reindex(agents))
A = A.dropna(subset=["oct"]); A["oct"]=A["oct"].astype(int).clip(1,8)
A["income"] = A["oct"].map(INCOME_MID)
BASES = {
  "Public surcharge$^{\\dagger}$": pub,
  "Home surcharge": home,
  "Universal RUC": vmt,
  "Corridor RUC (T5)": toll,
}
fig, ax = pf.newfig(7.6, 4.6)
mark = {"Public surcharge$^{\\dagger}$":"o","Home surcharge":"s","Universal RUC":"^","Corridor RUC (T5)":"D"}
colr = {"Public surcharge$^{\\dagger}$":pf.ORANGE,"Home surcharge":pf.BLUE,
        "Universal RUC":pf.GREEN,"Corridor RUC (T5)":"#0F7B6C"}
summary={}
for name, base in BASES.items():
    b = base.reindex(A.index).fillna(0.0)
    scale = RSTAR / (b.sum()*4/DAYS*365)          # equal-yield to R*
    A["pay"] = b*4/DAYS*365*scale/4               # annual per agent (undo x4: per-agent stays per-agent)
    # note: scale computed on x4 fleet total; per-agent payment uses same $ rate
    A["pay"] = b/DAYS*365*(RSTAR/ (b.sum()/DAYS*365*4))
    g = A.groupby("oct").apply(lambda x: (x.pay/x.income).mean()*100)
    ax.plot(g.index, g.values, "-"+mark[name], color=colr[name], lw=1.8, ms=6, label=name)
    summary[name]=(g.get(1,np.nan), g.get(8,np.nan))
# flat fee
A["pay"] = RSTAR/ (len(A)*4)
g = A.groupby("oct").apply(lambda x:(x.pay/x.income).mean()*100)
ax.plot(g.index, g.values, "-v", color=pf.GREY, lw=1.8, ms=6, label="Flat annual fee")
summary["Flat annual fee"]=(g.get(1,np.nan), g.get(8,np.nan))
ax.set_xlabel("household income category (1 = lowest, 8 = highest)")
ax.set_ylabel("mean burden (% of household income)")
ax.set_title("Equal-yield incidence: who pays $R^*$ under each instrument")
ax.legend(fontsize=8.5)
ax.grid(alpha=0.25)
pf.save(fig, OUT, "fig_incidence")
print("\nburden %income octile1 -> octile8 (regressivity ratio o1/o8):")
for k,(a,b) in summary.items():
    print(f"  {k:28s} {a:.2f}% -> {b:.2f}%   ratio {a/b:.1f}x")
for e in [".png",".pdf"]:
    (ROOT/"paper/validation_package/panels"/("fig_incidence"+e)).write_bytes((OUT/("fig_incidence"+e)).read_bytes())
print("synced")
