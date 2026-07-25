#!/usr/bin/env python3
"""Master TRB-quality figure suite for the shadow-gas-tax paper. Uniform Wong-palette
serif style (pubfig), 300 dpi, .pdf + .png. Uses ONLY converged runs (output_plans written).
Each figure showcases simulation or modeling power and maps to a paper/supplement slot.
-> paper/figures/trb/*.pdf|png
Run:  make_trb_figures.py    (regenerates whatever converged data exists)"""
import sys, glob, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
RUNS = ROOT / "scenarios/maryland/output/runs_2026"
OUT = REPO / "paper/figures/trb"; OUT.mkdir(parents=True, exist_ok=True)
TAB = REPO / "paper/tables"
DAYS, PLAN, RSTAR = 348.0, 3.0, 33.3
BLU, ORA, GRN, VER, PUR, GRY = pf.BLUE, pf.ORANGE, pf.GREEN, pf.VERM, pf.PURPLE, pf.GREY

def tou(ts):
    m = int((ts // 60) % 1440)
    return (0.7 if m < 360 else 1.6 if m < 480 else 1.47 if m < 600 else
            0.92 if m < 1020 else 1.14 if m < 1200 else 1.0 if m < 1320 else 0.7)

def sessions(run, conv=True):
    if conv and not (RUNS / run / "output_plans.xml.gz").exists():
        return None
    fs = sorted(glob.glob(str(RUNS / run / "ITERS/it.*/*.charging_sessions.csv")),
                key=lambda p: int(p.split("it.")[1].split("/")[0]))
    if not fs: return None
    d = pd.read_csv(fs[-1], sep=";")
    for c in ["energy_kwh","soc_start","soc_end","duration_s","walking_dist_m","time_start_s"]:
        if c in d: d[c] = pd.to_numeric(d[c], errors="coerce")
    return d

_DEM = None
def demo():
    global _DEM
    if _DEM is None:
        ev = pd.read_parquet(REPO / "pipeline/data/interim/ev_owners.parquet")
        _DEM = ev[["person_id","income","age","employment_status","home_ownership","hhsize","ev_powertrain"]].copy()
        _DEM["renter"] = (pd.to_numeric(_DEM.home_ownership, errors="coerce") == 2)
    return _DEM

BASE = sessions("baseline_pertype")
FIGN = [0]
def done(name): FIGN[0]+=1; print(f"  [{FIGN[0]:2d}] {name}")

# ============================================================ 1. charging composition
def fig_composition():
    d = BASE; e = d.energy_kwh
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 3.4))
    ven = d.groupby("charger_type_3way").energy_kwh.sum().reindex(["home","work","public"])
    ax[0].bar(range(3), ven/ven.sum()*100, color=[BLU,GRN,ORA], edgecolor="k", lw=0.4)
    ax[0].set_xticks(range(3)); ax[0].set_xticklabels(["Home","Work","Public"])
    for i,v in enumerate(ven/ven.sum()*100): ax[0].text(i, v+1.5, f"{v:.1f}%", ha="center", fontsize=9)
    ax[0].set(ylabel="% of charging energy", title="(a) Charging by venue", ylim=(0,92))
    typ = d[d.charger_type_3way=="public"].groupby("charger_type").energy_kwh.sum().reindex(["L2","DCFC","DCFC_TESLA"])
    ax[1].bar(range(3), typ/typ.sum()*100, color=[BLU,ORA,GRN], edgecolor="k", lw=0.4)
    ax[1].set_xticks(range(3)); ax[1].set_xticklabels(["L2","DCFC","Tesla"])
    for i,v in enumerate(typ/typ.sum()*100): ax[1].text(i, v+1.5, f"{v:.1f}%", ha="center", fontsize=9)
    ax[1].set(ylabel="% of public energy", title="(b) Public charging by type", ylim=(0,85))
    for a in ax: a.grid(axis="y", alpha=0.25)
    pf.save(fig, OUT, "fig01_charging_composition"); done("charging composition (venue + type)")

# ============================================================ 2. SOC dynamics
def fig_soc():
    d = BASE.merge(demo()[["person_id","ev_powertrain"]], on="person_id", how="left")
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 3.4))
    for lab,col in [("home",BLU),("public",ORA)]:
        s = d[d.charger_type_3way==lab].soc_start.dropna()*100
        ax[0].hist(s, bins=np.arange(0,101,5), density=True, alpha=0.55, color=col, label=lab, edgecolor="white", lw=0.3)
    ax[0].axvline(d.soc_start.mean()*100, color="k", ls="--", lw=0.8)
    ax[0].set(xlabel="battery SOC at charge start (%)", ylabel="density",
              title="(a) State of charge at plug-in"); ax[0].legend(fontsize=8, title="venue")
    dep = (d.soc_end - d.soc_start)*100
    for pt,col in [("BEV",BLU),("PHEV",ORA)]:
        s = dep[d.ev_powertrain==pt].dropna()
        if len(s): ax[1].hist(s, bins=np.arange(0,101,5), density=True, alpha=0.55, color=col, label=pt, edgecolor="white", lw=0.3)
    ax[1].set(xlabel="energy added per session (SOC pp)", ylabel="density",
              title="(b) Charge depth by powertrain"); ax[1].legend(fontsize=8)
    for a in ax: a.grid(alpha=0.25)
    pf.save(fig, OUT, "fig02_soc_dynamics"); done("SOC dynamics (plug-in SOC + charge depth)")

# ============================================================ 3. diurnal grid load
def fig_grid():
    d = BASE.copy(); d["h"] = (d.time_start_s//3600 % 24)
    load = d.groupby("h").energy_kwh.sum()/PLAN/1e3   # avg-day MW-ish (MWh/h)
    fig, ax = pf.newfig(6.6, 3.6)
    # ToU shading
    for a,b,c in [(0,6,"#e8f0e8"),(6,10,"#fbe6d5"),(17,20,"#fbe6d5"),(22,24,"#e8f0e8")]:
        ax.axvspan(a,b,color=c,alpha=0.6,lw=0)
    ax.plot(load.index, load.values, "-o", color=VER, ms=4, lw=2)
    pk=load.idxmax()
    ax.annotate(f"peak {load.max():.0f} MW @ {int(pk)}:00", (pk, load.max()),
                xytext=(pk-9, load.max()*0.86), fontsize=8.5, arrowprops=dict(arrowstyle="->", lw=0.7))
    ax.set(xlabel="hour of day", ylabel="fleet charging load (MW)",
           title="Simulated EV charging load profile (green = off-peak ToU)", xticks=range(0,25,3))
    ax.grid(alpha=0.25)
    pf.save(fig, OUT, "fig03_grid_load"); done("diurnal grid load + ToU windows")

# ============================================================ 4. captivity (renter vs owner)
def fig_captivity():
    d = BASE.groupby("person_id").apply(lambda x: pd.Series({
        "pub": x.loc[x.charger_type_3way=="public","energy_kwh"].sum(),
        "tot": x.energy_kwh.sum()})).reset_index()
    d = d.merge(demo()[["person_id","renter","income"]], on="person_id", how="left")
    d["pubshare"] = d.pub/d.tot.clip(lower=1e-9)*100
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 3.4))
    grp = d.groupby("renter").pubshare.mean()
    ax[0].bar([0,1], [grp.get(False,0),grp.get(True,0)], color=[BLU,VER], edgecolor="k", lw=0.4, width=0.6)
    ax[0].set_xticks([0,1]); ax[0].set_xticklabels(["Owner","Renter"])
    for i,v in enumerate([grp.get(False,0),grp.get(True,0)]): ax[0].text(i,v+0.5,f"{v:.1f}%",ha="center",fontweight="bold")
    ax[0].set(ylabel="public share of charging energy (%)", title="(a) Captivity by tenure")
    d["oct"] = pd.qcut(d.income.rank(method="first"), 8, labels=range(1,9))
    m = d.groupby("oct").pubshare.mean()
    ax[1].plot(range(1,9), m.values, "-o", color=GRN, ms=5)
    ax[1].set(xlabel="income octile (low→high)", ylabel="public share (%)", title="(b) Public reliance by income")
    for a in ax: a.grid(alpha=0.25)
    pf.save(fig, OUT, "fig04_captivity"); done("captivity: renter vs owner public reliance")

# ============================================================ 5. session characteristics
def fig_sessions():
    d = BASE
    fig, ax = plt.subplots(1, 3, figsize=(9.6, 3.2))
    types=["home","L2","DCFC","DCFC_TESLA"]; labs=["Home","L2","DCFC","Tesla"]; cols=[BLU,GRN,ORA,PUR]
    dur=[d[d.charger_type==t].duration_s.dropna()/60 for t in types]
    bp=ax[0].boxplot(dur, tick_labels=labs, showfliers=False, patch_artist=True)
    for p,c in zip(bp["boxes"],cols): p.set(facecolor=c, alpha=0.55)
    ax[0].set(ylabel="session duration (min)", title="(a) Duration by type")
    en=[d[d.charger_type==t].energy_kwh.dropna() for t in types]
    bp=ax[1].boxplot(en, tick_labels=labs, showfliers=False, patch_artist=True)
    for p,c in zip(bp["boxes"],cols): p.set(facecolor=c, alpha=0.55)
    ax[1].set(ylabel="energy per session (kWh)", title="(b) Energy by type")
    w=d[d.charger_type_3way=="public"].walking_dist_m.dropna()
    ax[2].hist(w, bins=np.arange(0,801,50), color=ORA, edgecolor="white", lw=0.3)
    ax[2].axvline(w.median(), color="k", ls="--", lw=0.8, label=f"median {w.median():.0f} m")
    ax[2].set(xlabel="walk to public charger (m)", ylabel="sessions", title="(c) Access friction"); ax[2].legend(fontsize=8)
    for a in ax: a.grid(alpha=0.25)
    pf.save(fig, OUT, "fig05_session_characteristics"); done("session duration/energy/walk by type")

# ============================================================ 6. instrument adequacy-equity plane
def fig_adequacy_equity():
    f = TAB / "policy_comparison.csv"
    if not f.exists(): print("  [skip] adequacy-equity (need policy_comparison.csv)"); return
    d = pd.read_csv(f)
    # (label, colour, marker, (dx,dy) label offset in points, ha)
    fam = {"gas_equiv":("Gas-tax equiv.",GRY,"D",(6,8),"left"),"ruc":("Flat RUC",GRN,"s",(6,-12),"left"),
           "flat_fee":("Flat fee",ORA,"^",(8,0),"left"),"md_actual":("MD fee",PUR,"P",(8,2),"left"),
           "T1_state_public_5c":("Charge +5¢",VER,"o",(6,7),"left"),
           "T2_state_public_10c":("Charge +10¢",VER,"o",(6,-13),"left"),
           "T3_utility_evrider_3c":("Home +3¢",VER,"o",(8,2),"left"),
           "T4_combined_5c_2c":("Combined",VER,"o",(8,2),"left")}
    fig, ax = pf.newfig(6.8, 4.4)
    for _,r in d.iterrows():
        nm,col,mk,off,ha = fam.get(r.instrument,(r.instrument,GRY,"o",(4,3),"left"))
        ax.scatter(r.rev_over_Rstar*100, r.suits, color=col, marker=mk, s=75, edgecolor="k", lw=0.5, zorder=5)
        ax.annotate(nm,(r.rev_over_Rstar*100,r.suits),xytext=off,textcoords="offset points",fontsize=7.5,ha=ha)
    ax.set_xlim(-8, 118)
    ax.axvline(100, color="k", ls="--", lw=0.8, alpha=0.6)
    ax.text(101, ax.get_ylim()[0]+0.005, "fully adequate →", fontsize=7.5, style="italic")
    ax.set(xlabel="adequacy (% of $R^*$ recovered)", ylabel="equity (Suits index; higher = fairer)",
           title="Adequacy–equity trade-off across instruments")
    ax.grid(alpha=0.25)
    pf.save(fig, OUT, "fig06_adequacy_equity"); done("adequacy-equity plane (all instruments)")

# ============================================================ 7. winners/losers + burden by group
def fig_incidence():
    f = TAB / "per_agent_burdens.parquet"
    if not f.exists(): print("  [skip] incidence (need per_agent_burdens)"); return
    b = pd.read_parquet(f)
    insts=[("gas_equiv","Gas-tax"),("ruc","RUC"),("flat_fee","Flat fee"),("md_actual","MD fee"),
           ("T2_state_public_10c","Charge +10¢"),("T3_utility_evrider_3c","Home +3¢")]
    fair=b.gas_equiv.values
    fig, ax = plt.subplots(1, 2, figsize=(8.2, 3.6))
    x=np.arange(len(insts))
    win=[(b[k].values<fair-1).mean()*100 for k,_ in insts]; los=[(b[k].values>fair+1).mean()*100 for k,_ in insts]
    ax[0].bar(x, win, color=GRN, edgecolor="k", lw=0.3, label="winners (< fair)")
    ax[0].bar(x, [-l for l in los], color=VER, edgecolor="k", lw=0.3, label="losers (> fair)")
    ax[0].axhline(0,color="k",lw=0.8); ax[0].set_xticks(x); ax[0].set_xticklabels([l for _,l in insts],rotation=25,ha="right",fontsize=8)
    ax[0].set(ylabel="% of EV owners", title="(a) Winners vs losers"); ax[0].legend(fontsize=8)
    b["oct"]=pd.qcut(b.income_usd.rank(method="first"),8,labels=range(1,9))
    for k,lab in [("ruc","RUC"),("flat_fee","Flat fee"),("md_actual","MD fee"),("T3_utility_evrider_3c","Home +3¢")]:
        m=(b[k]/b.income_usd*100).groupby(b.oct).mean()
        ax[1].plot(range(1,9), m.values, "-o", ms=4, label=lab)
    ax[1].set(xlabel="income octile (low→high)", ylabel="burden as % of income", title="(b) Effective rate by income")
    ax[1].legend(fontsize=7.5)
    for a in ax: a.grid(alpha=0.25)
    pf.save(fig, OUT, "fig07_incidence"); done("winners/losers + effective rate by income")

# ============================================================ 8. Laffer curves (delegate)
def fig_laffer():
    import subprocess
    # sweep_analysis writes laffer_public/home into paper/figures; copy the converged versions here
    subprocess.run([sys.executable, str(Path(__file__).parent/"sweep_analysis.py")], capture_output=True)
    for src in ["laffer_public","laffer_home"]:
        for ext in [".pdf",".png"]:
            s=REPO/"paper/figures"/(src+ext)
            if s.exists(): (OUT/(f"fig08_{src}"+ext)).write_bytes(s.read_bytes())
    done("Laffer curves (public + home) [home pending its runs]")

def main():
    print(f"[TRB figures] -> {OUT}")
    fig_composition(); fig_soc(); fig_grid(); fig_captivity(); fig_sessions()
    fig_adequacy_equity(); fig_incidence(); fig_laffer()
    n=len(list(OUT.glob("*.png")))
    print(f"\n[done] {n} figures in paper/figures/trb/  (300 dpi, .pdf + .png, Wong palette, serif)")

if __name__ == "__main__":
    main()
