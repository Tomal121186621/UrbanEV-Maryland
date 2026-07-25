#!/usr/bin/env python3
"""INDEPENDENT population validation vs Census ACS 2020-2024 5-year, Maryland statewide
(24 jurisdictions) — fully independent of the MWCOG RTS training survey. Bulk table-based
summary files (no API key). Universes handled honestly:
  - person-universe (B01001 age/sex): synth person-weighted, direct comparison
  - household-universe (B19001 income, B11016 size, B25003 tenure, B25024 dwelling):
    synthetic agents carry household attributes; person-weighting would over-count large
    households, so agents are reweighted by 1/hhsize to approximate household shares (noted).
  - ACS housing universe excludes group quarters; synth 'Dorm/inst' (<1%) excluded to match.
-> paper/figures/validation_trb/fig_val_acs.png + rows appended to validation summary"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

REPO = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
ACS = REPO/"pipeline/data/reference/acs2024"
OUT = REPO/"paper/figures/validation_trb"
ACSC, SYNC = pf.GREEN, pf.ORANGE

def acs_md(table):
    d = pd.read_csv(ACS/f"acsdt5y2024-{table}.dat", sep="|")
    d = d[d.GEO_ID.astype(str).str.startswith("0500000US24")]
    assert len(d) == 24, f"{table}: expected 24 MD jurisdictions, got {len(d)}"
    return d[[c for c in d.columns if c.endswith(tuple("0123456789")) and "_E" in c]].sum()

def cells(s, table, nums):  # sum estimate cells by number
    return sum(s[f"{table}_E{n:03d}"] for n in nums)

# ---------------- ACS marginals (MD statewide) ----------------
a = {}
# age bands (B01001, person universe): male 003-025, female 027-049
b = acs_md("b01001")
a["age_b"] = {"<25":  cells(b,"B01001",range(3,11))+cells(b,"B01001",range(27,35)),
              "25-34":cells(b,"B01001",[11,12])+cells(b,"B01001",[35,36]),
              "35-44":cells(b,"B01001",[13,14])+cells(b,"B01001",[37,38]),
              "45-54":cells(b,"B01001",[15,16])+cells(b,"B01001",[39,40]),
              "55-64":cells(b,"B01001",[17,18,19])+cells(b,"B01001",[41,42,43]),
              "65+":  cells(b,"B01001",range(20,26))+cells(b,"B01001",range(44,50))}
a["gender"] = {"Male": b["B01001_E002"], "Female": b["B01001_E026"]}
# income (B19001 -> survey 8 brackets)
i = acs_md("b19001")
a["hh_income_detailed"] = {"<$15k":cells(i,"B19001",[2,3]), "$15-25k":cells(i,"B19001",[4,5]),
    "$25-35k":cells(i,"B19001",[6,7]), "$35-50k":cells(i,"B19001",[8,9,10]),
    "$50-75k":cells(i,"B19001",[11,12]), "$75-100k":cells(i,"B19001",[13]),
    "$100-150k":cells(i,"B19001",[14,15]), "$150k+":cells(i,"B19001",[16,17])}
# household size (B11016: family 2-7+ = 003-008, nonfamily 1-7+ = 010-016)
h = acs_md("b11016")
a["hhsize"] = {"1": h["B11016_E010"],
               "2": h["B11016_E003"]+h["B11016_E011"], "3": h["B11016_E004"]+h["B11016_E012"],
               "4": h["B11016_E005"]+h["B11016_E013"], "5": h["B11016_E006"]+h["B11016_E014"],
               "6": h["B11016_E007"]+h["B11016_E015"], "7+": h["B11016_E008"]+h["B11016_E016"]}
# tenure (B25003) — ACS has owner/renter only
tn = acs_md("b25003")
a["home_ownership"] = {"Own": tn["B25003_E002"], "Rent": tn["B25003_E003"]}
# dwelling (B25024) — SF det 002, SF att 003, apt 004-009, mobile+other 010-011
dw = acs_md("b25024")
a["home_type"] = {"SF detached": dw["B25024_E002"], "SF attached": dw["B25024_E003"],
                  "Apt/Condo": cells(dw,"B25024",range(4,10)), "Mobile": cells(dw,"B25024",[10,11])}

# ---------------- synthetic side ----------------
syn = pd.read_parquet(REPO/"pipeline/data/interim/synth_person.parquet",
                      columns=["age","gender","hhsize","home_ownership","hh_income_detailed","home_type"])
syn["age_b"] = pd.cut(syn.age, [0,24,34,44,54,64,200], labels=["<25","25-34","35-44","45-54","55-64","65+"])
for c in ["gender","hhsize","home_ownership","hh_income_detailed","home_type"]:
    syn[c] = pd.to_numeric(syn[c], errors="coerce").round().astype("Int64").astype(str)
syn["hw"] = 1.0/pd.to_numeric(syn.hhsize, errors="coerce").clip(lower=1)   # household reweight
LBL = {"gender":{"1":"Female","2":"Male"},
       "home_ownership":{"1":"Own","2":"Rent","3":"Other"},
       "home_type":{"1":"SF detached","2":"SF attached","3":"Apt/Condo","4":"Mobile","5":"Dorm/inst"},
       "hh_income_detailed":{"1":"<$15k","2":"$15-25k","3":"$25-35k","4":"$35-50k","5":"$50-75k",
                             "6":"$75-100k","7":"$100-150k","8":"$150k+"},
       "hhsize":{**{str(k):str(k) for k in range(1,7)}, "7":"7+", "8":"7+"}}
def synth_marg(attr, hh_universe):
    s = syn.copy()
    if attr != "age_b": s[attr] = s[attr].map(LBL[attr])
    if attr == "home_ownership": s = s[s[attr] != "Other"]          # match ACS universe
    if attr == "home_type": s = s[s[attr] != "Dorm/inst"]           # ACS excludes group quarters
    w = s.hw if hh_universe else pd.Series(1.0, index=s.index)
    g = s.groupby(attr)[w.name if hh_universe else attr].agg("sum" if hh_universe else "size") if hh_universe else s.groupby(attr).size()
    if hh_universe: g = s.groupby(attr).hw.sum()
    return g/g.sum()

PANELS = [("age_b","Age band (persons)",False), ("gender","Gender (persons)",False),
          ("hh_income_detailed","Household income",True), ("hhsize","Household size",True),
          ("home_ownership","Tenure",True), ("home_type","Dwelling type",True)]
def tvd(p,q): return 0.5*np.abs(p-q).sum()

fig, axes = plt.subplots(2, 3, figsize=(12.5, 6.6)); axes = axes.ravel()
res = []
for ax,(attr,lab,hhu) in zip(axes, PANELS):
    am = pd.Series(a[attr], dtype=float); am = am/am.sum()
    sm = synth_marg(attr, hhu).reindex(am.index, fill_value=0)
    t = tvd(am.values, sm.values); res.append((lab, t))
    x = np.arange(len(am))
    ax.bar(x-0.2, am.values*100, 0.4, label="ACS 2020–2024 MD", color=ACSC, edgecolor="k", lw=0.3)
    ax.bar(x+0.2, sm.values*100, 0.4, label="synthetic", color=SYNC, edgecolor="k", lw=0.3)
    ax.set_xticks(x); ax.set_xticklabels(am.index, fontsize=7.5, rotation=35, ha="right")
    ax.set_title(f"{lab}  (TVD={t:.3f})", fontsize=10)
    ax.set_ylabel("% share", fontsize=8); ax.grid(axis="y", alpha=0.25); ax.tick_params(labelsize=8)
h,l = axes[0].get_legend_handles_labels()
fig.legend(h, l, loc="upper center", ncol=2, fontsize=10, frameon=False, bbox_to_anchor=(0.5, 0.97))
fig.suptitle("Independent census validation: synthetic population vs ACS 2020–2024 Maryland "
             f"(mean TVD={np.mean([r[1] for r in res]):.3f})", fontsize=12, fontweight="bold", y=1.0)
fig.tight_layout(rect=(0,0,1,0.93))
fig.savefig(OUT/"fig_val_acs.png", dpi=300); fig.savefig(OUT/"fig_val_acs.pdf")
plt.close(fig)
for lab,t in res: print(f"  {lab:26s} TVD={t:.3f}")
print(f"mean TVD vs ACS: {np.mean([r[1] for r in res]):.3f}")
print("-> fig_val_acs.png")
