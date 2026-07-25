#!/usr/bin/env python3
"""Merged population-marginals validation: THREE bars per category —
survey (held-out TEST, weighted) vs synthetic vs Census ACS 2020-2024 MD (independent).
Universe handling (honest): age/gender = person-universe (person weights);
income/hhsize/vehicles/tenure/dwelling = household-universe (survey: household weights on
survey_hh TEST; synthetic: agents reweighted 1/hhsize; ACS native households).
Employment/workers panels keep survey-vs-synth only (ACS table not pulled) and say so.
OVERWRITES fig_val_population_marginals.png (+pdf)."""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

REPO = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
INT = REPO/"pipeline/data/interim"; ACS = REPO/"pipeline/data/reference/acs2024"
OUT = REPO/"paper/figures/validation_trb"
SURVEY, SYNTH, ACSC = pf.BLUE, pf.ORANGE, pf.GREEN

# ---------- ACS (MD statewide) ----------
def acs_md(table):
    d = pd.read_csv(ACS/f"acsdt5y2024-{table}.dat", sep="|")
    d = d[d.GEO_ID.astype(str).str.startswith("0500000US24")]
    return d[[c for c in d.columns if "_E" in c]].sum()
def cells(s, t, nums): return sum(s[f"{t}_E{n:03d}"] for n in nums)
b = acs_md("b01001"); i = acs_md("b19001"); h = acs_md("b11016"); tn = acs_md("b25003")
dw = acs_md("b25024"); vv = acs_md("b08201")
A = {
 "age_b": {"<25":cells(b,"B01001",range(3,11))+cells(b,"B01001",range(27,35)),
           "25-34":cells(b,"B01001",[11,12])+cells(b,"B01001",[35,36]),
           "35-44":cells(b,"B01001",[13,14])+cells(b,"B01001",[37,38]),
           "45-54":cells(b,"B01001",[15,16])+cells(b,"B01001",[39,40]),
           "55-64":cells(b,"B01001",[17,18,19])+cells(b,"B01001",[41,42,43]),
           "65+":cells(b,"B01001",range(20,26))+cells(b,"B01001",range(44,50))},
 "gender": {"Female":b["B01001_E026"], "Male":b["B01001_E002"]},
 "hh_income_detailed": {"<$15k":cells(i,"B19001",[2,3]),"$15-25k":cells(i,"B19001",[4,5]),
    "$25-35k":cells(i,"B19001",[6,7]),"$35-50k":cells(i,"B19001",[8,9,10]),
    "$50-75k":cells(i,"B19001",[11,12]),"$75-100k":cells(i,"B19001",[13]),
    "$100-150k":cells(i,"B19001",[14,15]),"$150k+":cells(i,"B19001",[16,17])},
 "hhsize": {"1":h["B11016_E010"],"2":h["B11016_E003"]+h["B11016_E011"],
            "3":h["B11016_E004"]+h["B11016_E012"],"4":h["B11016_E005"]+h["B11016_E013"],
            "5":h["B11016_E006"]+h["B11016_E014"],"6":h["B11016_E007"]+h["B11016_E015"],
            "7+":h["B11016_E008"]+h["B11016_E016"]},
 "numvehicle": {"0":vv["B08201_E002"],"1":vv["B08201_E003"],"2":vv["B08201_E004"],
                "3":vv["B08201_E005"],"4+":vv["B08201_E006"]},
 "home_ownership": {"Own":tn["B25003_E002"],"Rent":tn["B25003_E003"]},
 "home_type": {"SF detached":dw["B25024_E002"],"SF attached":dw["B25024_E003"],
               "Apt/Condo":cells(dw,"B25024",range(4,10)),"Mobile":cells(dw,"B25024",[10,11])},
}

# ---------- survey (TEST) + synthetic ----------
sp = pd.read_parquet(INT/"survey_person.parquet"); sh = pd.read_parquet(INT/"survey_hh.parquet")
sv = sp.merge(sh, on="household_id", how="left", suffixes=("","_hh")); sv = sv[sv.split=="test"]
svh = sh[sh.split=="test"].copy()                                  # household frame (TEST)
syn = pd.read_parquet(INT/"synth_person.parquet",
        columns=["age","gender","hhsize","numworkers","numvehicle","home_ownership",
                 "hh_income_detailed","home_type","employment_status"]).sample(600_000, random_state=1)
def norm(s):
    n = pd.to_numeric(s, errors="coerce")
    return n.round().astype("Int64").astype(str) if n.notna().mean()>0.9 else s.astype(str)
for c in ["gender","hhsize","numworkers","numvehicle","home_ownership","hh_income_detailed","home_type","employment_status"]:
    if c in sv: sv[c]=norm(sv[c])
    if c in svh: svh[c]=norm(svh[c])
    if c in syn: syn[c]=norm(syn[c])
sv["age_b"]=pd.cut(sv.age,[0,24,34,44,54,64,200],labels=["<25","25-34","35-44","45-54","55-64","65+"]).astype(str)
syn["age_b"]=pd.cut(syn.age,[0,24,34,44,54,64,200],labels=["<25","25-34","35-44","45-54","55-64","65+"]).astype(str)
syn["hw"]=1.0/pd.to_numeric(syn.hhsize,errors="coerce").clip(lower=1)

LBL = {"gender":{"1":"Female","2":"Male"},
 "employment_status":{"0":"Worker","1":"Retired","2":"Volunteer","3":"Homemaker","4":"Unemp.(seek)",
                      "5":"Unemp.(not)","6":"Student","7":"Disabled","8":"Under-16"},
 "home_type":{"1":"SF detached","2":"SF attached","3":"Apt/Condo","4":"Mobile","5":"Dorm/inst"},
 "home_ownership":{"1":"Own","2":"Rent","3":"Other"},
 "hh_income_detailed":{"1":"<$15k","2":"$15-25k","3":"$25-35k","4":"$35-50k","5":"$50-75k",
                       "6":"$75-100k","7":"$100-150k","8":"$150k+"},
 "hhsize":{**{str(k):str(k) for k in range(1,7)},"7":"7+","8":"7+"},
 "numvehicle":{**{str(k):str(k) for k in range(0,4)},**{str(k):"4+" for k in range(4,10)}}}
def relab(s, attr): return s.map(LBL[attr]) if attr in LBL else s
def marg(df, attr, w):
    d = df.copy(); d["_c"] = relab(d[attr], attr)
    d = d[~d._c.isin(["Other","Dorm/inst","None","nan","<NA>"])]
    g = d.groupby("_c").apply(lambda x: x[w].sum()) if w else d.groupby("_c").size()
    return g/g.sum()
def tvd(p,q): return 0.5*np.abs(p-q).sum()

# (attr, label, universe: 'p' person / 'h' household, acs available)
PANELS=[("age_b","Age band","p",True),("gender","Gender","p",True),
        ("employment_status","Employment","p",False),
        ("hh_income_detailed","Household income","h",True),("hhsize","Household size","h",True),
        ("numvehicle","Vehicles","h",True),("numworkers","Workers","h",False),
        ("home_ownership","Tenure","h",True),("home_type","Dwelling type","h",True)]
fig, axes = plt.subplots(3, 3, figsize=(12.8, 10)); axes=axes.ravel()
tv_s, tv_a = [], []
for ax,(attr,lab,uni,has_acs) in zip(axes, PANELS):
    if uni=="p":
        smarg = marg(sv, attr, "wtperfin"); ymarg = marg(syn, attr, None)
    else:
        src = svh if attr in svh.columns else sv
        smarg = marg(src, attr, "wthhfin" if attr in svh.columns else "wtperfin")
        ymarg = marg(syn, attr, "hw")
    idx = list(smarg.index)
    if attr=="age_b": idx=[c for c in ["<25","25-34","35-44","45-54","55-64","65+"] if c in idx]
    elif attr in ("hhsize","numvehicle","numworkers"): idx=sorted(idx, key=lambda v:(len(str(v)),str(v)))
    elif attr=="hh_income_detailed": idx=[LBL[attr][str(k)] for k in range(1,9) if LBL[attr][str(k)] in idx]
    elif attr=="home_type": idx=[c for c in ["SF detached","SF attached","Apt/Condo","Mobile"] if c in idx]
    elif attr=="employment_status": idx=[c for c in ["Worker","Retired","Student","Homemaker","Volunteer","Unemp.(seek)","Unemp.(not)","Disabled","Under-16"] if c in idx]
    am = None
    if has_acs:
        am = pd.Series(A[attr], dtype=float); am=am/am.sum()
        idx = [c for c in idx if c in am.index] + [c for c in am.index if c not in idx]
    smarg=smarg.reindex(idx,fill_value=0); ymarg=ymarg.reindex(idx,fill_value=0)
    x=np.arange(len(idx)); wbar=0.27 if has_acs else 0.4
    ax.bar(x-wbar, smarg.values*100, wbar, label="survey (weighted)", color=SURVEY, edgecolor="k", lw=0.3)
    ax.bar(x, ymarg.values*100, wbar, label="synthetic", color=SYNTH, edgecolor="k", lw=0.3)
    t_s = tvd(smarg.values, ymarg.values); tv_s.append(t_s); ttl=f"{lab}  (TVD survey {t_s:.3f}"
    print(f"TVDCHECK survey {attr}: {t_s:.4f}")
    if has_acs:
        am=am.reindex(idx,fill_value=0)
        ax.bar(x+wbar, am.values*100, wbar, label="ACS 2020-2024 MD", color=ACSC, edgecolor="k", lw=0.3)
        t_a = tvd(am.values, ymarg.values); tv_a.append(t_a); ttl+=f", ACS {t_a:.3f}"
        print(f"TVDCHECK acs {attr}: {t_a:.4f}")
    else:
        ax.text(0.97,0.92,"ACS: n/a", transform=ax.transAxes, fontsize=7.5, ha="right", style="italic", color=pf.GREY)
    ax.set_title(ttl+")", fontsize=9.5)
    ax.set_xticks(x); ax.set_xticklabels(idx, fontsize=7.5, rotation=35, ha="right")
    ax.set_ylabel("% share", fontsize=8); ax.grid(axis="y", alpha=0.25); ax.tick_params(labelsize=8)
h_,l_ = axes[3].get_legend_handles_labels()
fig.legend(h_, l_, loc="upper center", ncol=3, fontsize=10, frameon=False, bbox_to_anchor=(0.5,0.975))
fig.suptitle("Population validation: synthetic vs held-out survey (weighted) vs independent Census ACS\n"
             f"(mean TVD: survey {np.mean(tv_s):.3f}, ACS {np.mean(tv_a):.3f}; person-universe: age/gender/employment; household-universe: others)",
             fontsize=11.5, fontweight="bold", y=1.0)
fig.tight_layout(rect=(0,0,1,0.94))
print(f"TVDCHECK MEAN survey {np.mean(tv_s):.4f} acs {np.mean(tv_a):.4f}")
fig.savefig(OUT/"fig_val_population_marginals.png", dpi=300)
fig.savefig(OUT/"fig_val_population_marginals.pdf")
plt.close(fig)
print(f"mean TVD vs survey {np.mean(tv_s):.3f} | vs ACS {np.mean(tv_a):.3f}")
print("-> fig_val_population_marginals.png (3-bar merged)")
