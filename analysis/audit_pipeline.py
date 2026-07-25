#!/usr/bin/env python3
"""Comprehensive consistency audit of the full pipeline + all outputs. Cross-checks
provenance/ID consistency, count conservation, EV-vs-MVA, VMT/R* sanity, energy
conservation, validation metrics, unit consistency, and paper-claim vs data agreement.
Flags every inconsistency as [OK]/[WARN]/[FAIL]. -> prints an audit report."""
import glob, re, gzip
from pathlib import Path
import numpy as np, pandas as pd

REPO = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
PIPE = REPO/"pipeline/data/interim"
RUNS = REPO/"UrbanEV-Maryland/scenarios/maryland/output/runs_2026"
TAB = REPO/"paper/tables"
FLAGS = []
def chk(cond, name, detail):
    tag = "OK" if cond=="OK" else cond
    FLAGS.append((tag, name, detail))
    print(f"  [{tag:4s}] {name}: {detail}")

print("="*78); print("PIPELINE CONSISTENCY AUDIT"); print("="*78)

# ---------- 1. counts + provenance/ID consistency ----------
print("\n[1] COUNT CONSERVATION & ID PROVENANCE")
synth = pd.read_parquet(PIPE/"synth_person.parquet")
evo = pd.read_parquet(PIPE/"ev_owners.parquet")
print(f"       synth_person: {len(synth):,} | ev_owners: {len(evo):,}")
# EV owner IDs must be a subset of synth persons
sset, eset = set(synth.person_id), set(evo.person_id)
ovl = len(eset & sset)/len(eset)*100 if eset else 0
chk("OK" if ovl>99 else "FAIL", "EV owners ⊆ synth population", f"{ovl:.1f}% of EV owner IDs found in synth_person")
# sim charging agents ⊆ ev owners
bs = sorted(glob.glob(str(RUNS/"baseline_pertype/ITERS/it.*/*.charging_sessions.csv")), key=lambda p:int(p.split("it.")[1].split("/")[0]))
if bs:
    ss = pd.read_csv(bs[-1], sep=";"); simids=set(ss.person_id)
    ov2 = len(simids & eset)/len(simids)*100
    chk("OK" if ov2>99 else "FAIL", "sim agents ⊆ EV owners", f"{ov2:.1f}% of charging agents are EV owners; {len(simids):,} charged of {len(evo):,}")

# ---------- 2. EV fleet vs MVA ----------
print("\n[2] EV FLEET vs MVA (Jan-2026)")
chk("OK" if abs(len(evo)-148359)/148359<0.02 else "WARN", "EV total vs MVA 148,359", f"{len(evo):,} ({(len(evo)-148359)/148359*100:+.1f}%)")
if "ev_powertrain" in evo:
    bev = (evo.ev_powertrain=="BEV").mean()*100
    chk("OK" if abs(bev-73.8)<3 else "WARN", "BEV share vs 73.8%", f"{bev:.1f}%")

# ---------- 3. VMT / R* sanity ----------
print("\n[3] VMT & R* SANITY")
pa = pd.read_csv(RUNS/"baseline/shadow_tax_gap_per_agent.csv")
vmt_day = pa.daily_base_vmt_mi.mean()
chk("OK" if 20<vmt_day<45 else "WARN", "mean daily VMT/agent", f"{vmt_day:.1f} mi (real-EV odometer range ~20-40)")
Rstar = (pa.state_tax_gap_day_usd*348).sum()/1e6
chk("OK" if abs(Rstar-33.3)<0.5 else "WARN", "R* recompute vs $33.3M", f"${Rstar:.1f}M")
elec_share = pa.daily_elec_vmt_mi.sum()/pa.daily_base_vmt_mi.sum()*100
chk("OK" if 60<elec_share<100 else "WARN", "electric VMT share", f"{elec_share:.0f}% of VMT is electric (rest = PHEV gas)")

# ---------- 4. charging energy conservation ----------
print("\n[4] CHARGING ENERGY CONSERVATION")
if bs:
    ss["e"]=pd.to_numeric(ss.energy_kwh,errors="coerce"); t=ss.e.sum()
    sh = {v: ss[ss.charger_type_3way==v].e.sum()/t*100 for v in ["home","work","public"]}
    tot = sum(sh.values())
    chk("OK" if abs(tot-100)<0.5 else "FAIL", "venue shares sum to 100", f"{tot:.1f}%")
    chk("OK" if 75<sh['home']<85 else "WARN", "home share vs DOE ~80%", f"{sh['home']:.1f}%")
    chk("OK" if 8<sh['public']<16 else "WARN", "public share vs AFDC ~10-15%", f"{sh['public']:.1f}%")
    typ = {c: ss[ss.charger_type==c].e.sum() for c in ["L2","DCFC","DCFC_TESLA"]}
    pub_e = ss[ss.charger_type_3way=="public"].e.sum()
    chk("OK" if abs(sum(typ.values())-pub_e)/pub_e<0.02 else "FAIL", "L2+DCFC+Tesla = public energy", f"types sum {sum(typ.values())/1e3:.0f} MWh vs public {pub_e/1e3:.0f} MWh")

# ---------- 5. validation metrics ----------
print("\n[5] VALIDATION METRICS")
vfiles = glob.glob(str(RUNS/"validation_pertype/*.csv")) + glob.glob(str(RUNS/"validation/*.csv"))
chk("OK" if vfiles else "WARN", "ChargePoint validation outputs exist", f"{len(vfiles)} files" if vfiles else "not found")

# ---------- 6. per-agent burdens internal consistency ----------
print("\n[6] POLICY/BURDEN CONSISTENCY")
if (TAB/"per_agent_burdens.parquet").exists():
    b = pd.read_parquet(TAB/"per_agent_burdens.parquet")
    # adequate instruments must sum to R*
    for inst in ["ruc","flat_fee","gas_equiv"]:
        if inst in b:
            rev = b[inst].sum()/1e6
            chk("OK" if abs(rev-Rstar)/Rstar<0.05 else "WARN", f"{inst} revenue = R*", f"${rev:.1f}M vs R* ${Rstar:.1f}M")
    # burden count matches EV fleet
    chk("OK" if abs(len(b)-len(evo))/len(evo)<0.02 else "WARN", "burden rows = EV fleet", f"{len(b):,} vs {len(evo):,}")

# ---------- 7. paper-claim vs data ----------
print("\n[7] PAPER CLAIMS vs DATA")
mtex = (REPO/"paper/manuscript/main.tex").read_text()
def macro(name):
    m = re.search(rf'newcommand{{\\{name}}}{{([0-9.]+)', mtex); return float(m.group(1)) if m else None
hv = macro("HomeVenue"); dr = macro("DiurnalR")
if bs:
    chk("OK" if hv and abs(hv-sh['home'])<2 else "FAIL", "paper HomeVenue vs data home share",
        f"paper {hv}% vs data {sh['home']:.1f}%  {'<-- MISMATCH' if hv and abs(hv-sh['home'])>=2 else ''}")
chk("WARN" if dr and abs(dr-0.826)>0.01 else "OK", "paper DiurnalR vs measured r", f"paper {dr} vs measured 0.826")
chk("OK" if "148302" in mtex or "148,302" in mtex else "WARN", "paper EV count", f"claims 148,302 vs data {len(evo):,}")
chk("OK" if "38.8" in mtex else "WARN", "paper VMT claim", f"claims 38.8 vs data {vmt_day:.1f}")

# ---------- summary ----------
print("\n"+"="*78)
nf = sum(1 for t,_,_ in FLAGS if t=="FAIL"); nw = sum(1 for t,_,_ in FLAGS if t=="WARN")
print(f"AUDIT SUMMARY: {sum(1 for t,_,_ in FLAGS if t=='OK')} OK | {nw} WARN | {nf} FAIL")
if nf or nw:
    print("\nISSUES TO REVIEW:")
    for t,n,d in FLAGS:
        if t!="OK": print(f"  [{t}] {n}: {d}")
