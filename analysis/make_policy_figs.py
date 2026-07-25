#!/usr/bin/env python3
"""Paper Figures 3 & 4 from the converged sweep:
   fig_laffer_pair : public + home surcharge revenue curves vs R* (base erosion on 2nd axis)
   fig_policy_ladder : all instruments' revenue vs R*
-> paper/figures/trb + validation_package/panels"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, "/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB/UrbanEV-Maryland/analysis")
import pubfig as pf
import matplotlib.pyplot as plt

ROOT=Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
R=ROOT/"UrbanEV-Maryland/scenarios/maryland/output/runs_2026"
OUT=ROOT/"paper/figures/trb"; OUT.mkdir(parents=True, exist_ok=True)
S,D=4,3; RSTAR=33.3
PUB=["L2","DCFC","DCFC_TESLA"]
def kwh(run,t):
    d=pd.read_csv(R/run/"ITERS/it.50/50.charging_sessions.csv",sep=";")
    return d[d.charger_type.isin(t)].energy_kwh.sum()
ann=lambda k,c: k*S/D*365*c/1e6
bp=kwh("gasfb4_baseline_25pct",PUB); bh=kwh("gasfb4_baseline_25pct",["home"])

pubC=[0,10,25,50,100,200]
pubQ=[bp]+[kwh(f"sw_pub_{c}c",PUB) for c in pubC[1:]]
pubRev=[ann(q,c/100) for q,c in zip(pubQ,pubC)]
homC=[0,10,22,40]
homQ=[bh]+[kwh(f"sw_home_{c}c",["home"]) for c in homC[1:]]
homRev=[ann(q,c/100) for q,c in zip(homQ,homC)]

fig,axs=plt.subplots(1,2,figsize=(11,4.3))
for ax,C,Q,Rev,base,ttl,col in [
    (axs[0],pubC,pubQ,pubRev,bp,"(a) Public charging surcharge",pf.ORANGE),
    (axs[1],homC,homQ,homRev,bh,"(b) Home charging surcharge",pf.BLUE)]:
    ax.plot(C,Rev,"-o",color=col,lw=2,ms=6,zorder=3,label="revenue")
    ax.axhline(RSTAR,color=pf.VERM,ls="--",lw=1.6)
    ax.text(C[-1]*0.99,RSTAR+1.2,"$R^*$ = \\$33.3M",ha="right",fontsize=10,color=pf.VERM)
    ax2=ax.twinx()
    ax2.plot(C,[q/base*100-100 for q in Q],"-s",color=pf.GREY,lw=1.2,ms=4,alpha=0.8)
    ax2.set_ylabel("taxed energy vs baseline (%)",fontsize=9,color=pf.GREY)
    ax2.tick_params(labelsize=8,colors=pf.GREY)
    ax.set_xlabel("surcharge (¢/kWh)"); ax.set_ylabel("annual revenue ($M)")
    ax.set_title(ttl); ax.grid(alpha=0.25)
axs[0].set_ylim(0,40); axs[1].set_ylim(0,92)
fig.tight_layout()
fig.savefig(OUT/"fig_laffer_pair.png",dpi=300); fig.savefig(OUT/"fig_laffer_pair.pdf")
plt.close(fig); print("[laffer] done")

# ladder — instrument revenues (toll bars provisional until remap rerun)
t=lambda r,c: kwh(f"sw_{r}",PUB)*S/D*365*c/1e6
lab_rev=[
 ("Public +5¢ (T1)",           ann(kwh("sw_T1",PUB),0.05), pf.ORANGE),
 ("Public +10¢ (T2)",          ann(kwh("sw_T2",PUB),0.10), pf.ORANGE),
 ("Public +200¢ (ceiling)",    ann(kwh("sw_pub_200c",PUB),2.0), pf.ORANGE),
 ("Home +3¢ (T3)",             ann(kwh("sw_T3",["home"]),0.03), pf.BLUE),
 ("Home +2¢ & public +5¢ (T4)",ann(kwh("sw_T4",["home"]),0.02)+ann(kwh("sw_T4",PUB),0.05), pf.BLUE),
 ("Home +12¢ (closes $R^*$)",  RSTAR, pf.BLUE),
 ("Flat annual fee \\$225/EV", RSTAR, pf.GREY),
 ("Universal RUC 1.6¢/mi",     RSTAR, pf.GREEN),
 ("Interstate RUC 3.0¢/mi (T6)", 31.1, pf.GREEN),
 ("Corridor RUC 5.7¢/mi (T5)",  30.4, pf.GREEN),
]
fig,ax=pf.newfig(8.6,4.8)
y=np.arange(len(lab_rev))[::-1]
ax.barh(y,[v for _,v,_ in lab_rev],height=0.66,
        color=[c for _,_,c in lab_rev],edgecolor="k",lw=0.5)
for yi,(l,v,_) in zip(y,lab_rev):
    ax.text(v+0.6,yi,f"{v:.1f}",va="center",fontsize=9)
ax.axvline(RSTAR,color=pf.VERM,ls="--",lw=1.8)
ax.text(RSTAR+0.4,len(lab_rev)-0.5,"$R^*$",color=pf.VERM,fontsize=11,fontweight="bold")
ax.set_yticks(y); ax.set_yticklabels([l for l,_,_ in lab_rev],fontsize=9.5)
ax.set_xlabel("annual revenue ($M)")
ax.set_xlim(0,40)
from matplotlib.patches import Patch
ax.legend(handles=[Patch(fc=pf.ORANGE,ec="k",label="public surcharge"),
                   Patch(fc=pf.BLUE,ec="k",label="home surcharge"),
                   Patch(fc=pf.GREEN,ec="k",label="mileage-based"),
                   Patch(fc=pf.GREY,ec="k",label="flat fee")],fontsize=8.5,loc="upper right")
ax.set_title("Revenue-recovery instruments vs the shadow gas-tax gap")
pf.save(fig,OUT,"fig_policy_ladder")
print("[ladder] done")
for f in ["fig_laffer_pair","fig_policy_ladder"]:
    for e in [".png",".pdf"]:
        (ROOT/"paper/validation_package/panels"/(f+e)).write_bytes((OUT/(f+e)).read_bytes())
print("synced")
