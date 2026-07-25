#!/usr/bin/env python3
"""
synthesis_figs.py — cross-instrument synthesis figures for the TRB paper. Merges all
recovery instruments (charging surcharges, MD $125 flat fee, flat RUC, road-class and
corridor VMT fees) from the analysis tables into two headline figures:
  (1) adequacy x equity scatter — % of R* recovered vs Suits index (no instrument is both
      fully adequate and progressive; interstate-only RUC is the least-bad corner);
  (2) Suits-index comparison bar across every instrument.
Uses only the pre-computed tables (congestion-independent). Output -> paper/figures/.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
T = REPO / "paper/tables"; FIG = REPO / "paper/figures"
RSTAR = 33.3

# ---- assemble a unified instrument table: name, family, pct_R*, suits ----
rows = []
pc = pd.read_csv(T / "policy_comparison.csv")
LAB = {"gas_equiv": "Gas-tax equivalent", "ruc": "Flat RUC (per-mile)",
       "flat_fee": "Flat fee ($224/yr)", "md_actual": "MD EV fee ($125/$100)",
       "T1_state_public_5c": "Charging: public +5¢", "T2_state_public_10c": "Charging: public +10¢",
       "T3_utility_evrider_3c": "Charging: home +3¢", "T4_combined_5c_2c": "Charging: combined"}
FAM = {"gas_equiv": "benchmark", "ruc": "road-use", "flat_fee": "registration",
       "md_actual": "registration", "T1_state_public_5c": "charging",
       "T2_state_public_10c": "charging", "T3_utility_evrider_3c": "charging",
       "T4_combined_5c_2c": "charging"}
for _, r in pc.iterrows():
    rows.append(dict(name=LAB.get(r.instrument, r.instrument), family=FAM.get(r.instrument, "other"),
                     pct=r.rev_over_Rstar * 100, suits=r.suits))
# road-class VMT fees (each recovers R* = 100%)
rc = pd.read_csv(T / "road_vmt_fee.csv")
RCLAB = {"interstate_only": "VMT: interstate-only", "interstate+arterial": "VMT: interstate+arterial",
         "flat_RUC": None}   # flat_RUC duplicates 'ruc'
for _, r in rc.iterrows():
    if RCLAB.get(r.instrument):
        rows.append(dict(name=RCLAB[r.instrument], family="road-use", pct=100.0, suits=r.suits))
# corridor VMT fees
cor = pd.read_csv(T / "corridor_vmt_fee.csv")
for _, r in cor.iterrows():
    rows.append(dict(name=f"VMT: {r.scenario.split(' (')[0]}", family="road-use",
                     pct=100.0, suits=r.suits))
df = pd.DataFrame(rows)
df.to_csv(T / "instrument_synthesis.csv", index=False)

COL = {"charging": pf.VERM, "registration": pf.ORANGE, "road-use": pf.GREEN,
       "benchmark": pf.GREY}

# ---- Figure 1: adequacy x equity scatter ----
fig, ax = pf.newfig(7.0, 4.6)
ax.axvspan(95, 135, color=pf.GREEN, alpha=0.06)                     # "adequate" band
ax.axhline(0, color="k", lw=0.6, ls=":")
for fam in ["charging", "registration", "road-use", "benchmark"]:
    s = df[df.family == fam]
    ax.scatter(s.pct, s.suits, s=70, color=COL[fam], edgecolor="k", lw=0.5,
               label=fam, zorder=3)
# annotate the key instruments
key = {"VMT: interstate-only": (6, 8), "MD EV fee ($125/$100)": (6, -6),
       "Charging: home +3¢": (6, 6), "Charging: public +10¢": (6, -4),
       "Flat fee ($224/yr)": (-8, -14), "VMT: I-95": (4, 6)}
for _, r in df.iterrows():
    if r["name"] in key:
        dx, dy = key[r["name"]]
        ax.annotate(r["name"], (r.pct, r.suits), textcoords="offset points",
                    xytext=(dx, dy), fontsize=7.2, color="#222222")
ax.set_xlabel("Adequacy — % of shadow gas-tax gap R* recovered")
ax.set_ylabel("Suits index  (− = regressive)")
ax.set_title("No instrument is both fully adequate and progressive", fontsize=12)
ax.text(115, 0.006, "adequate", fontsize=8, color=pf.GREEN, ha="center", style="italic")
pf.legout(ax); pf.save(fig, FIG, "adequacy_equity_scatter")

# ---- Figure 2: Suits-index comparison bar (sorted) ----
d2 = df.drop_duplicates("name").sort_values("suits")
fig, ax = pf.newfig(7.0, 5.0)
colors = [COL[f] for f in d2.family]
ax.barh(range(len(d2)), d2.suits, color=colors, edgecolor="k", lw=0.3)
ax.set_yticks(range(len(d2))); ax.set_yticklabels(d2.name, fontsize=8)
ax.axvline(0, color="k", lw=0.8)
ax.set_xlabel("Suits index  (more negative = more regressive)")
ax.set_title("Progressivity of EV road-funding recovery instruments")
from matplotlib.patches import Patch
handles = [Patch(facecolor=COL[f], edgecolor="k", label=f) for f in
           ["charging", "registration", "road-use", "benchmark"]]
ax.legend(handles=handles, loc="lower left", fontsize=8, frameon=True)
pf.save(fig, FIG, "suits_comparison")
print(df.sort_values(["family", "suits"]).to_string(index=False))
print(f"\n[done] synthesis -> {FIG}/adequacy_equity_scatter.png, suits_comparison.png")
