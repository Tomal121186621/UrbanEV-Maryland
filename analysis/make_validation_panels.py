#!/usr/bin/env python3
"""Uniform, TRB-styled validation panels regenerated FROM DATA (not stitched PNGs).
Synthetic population vs the HELD-OUT survey TEST split (weighted) — no fabrication.
  fig_val_population_marginals.png : grouped bars survey(weighted) vs synth per attribute + TVD
  fig_val_joint_associations.png   : Cramer's V association matrices (survey, synth, error)
-> paper/figures/validation_trb/*.png|pdf   (Wong palette, serif, 300 dpi)"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

REPO = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
INT = REPO/"pipeline/data/interim"
OUT = REPO/"paper/figures/validation_trb"; OUT.mkdir(parents=True, exist_ok=True)
SURVEY, SYNTH = pf.BLUE, pf.ORANGE          # observed vs synthetic (Wong)

# ---- load: survey person+hh (TEST split, weighted) vs synth ----
sp = pd.read_parquet(INT/"survey_person.parquet")
sh = pd.read_parquet(INT/"survey_hh.parquet")
syn = pd.read_parquet(INT/"synth_person.parquet").sample(600_000, random_state=1)
sv = sp.merge(sh, on="household_id", how="left", suffixes=("","_hh"))
sv = sv[sv.split == "test"].copy()          # held-out test only
w = "wtperfin" if "wtperfin" in sv else ("wthhfin" if "wthhfin" in sv else None)
sv["w"] = sv[w] if w else 1.0

def age_band(a):
    b = pd.cut(a, [0,24,34,44,54,64,200], labels=["<25","25-34","35-44","45-54","55-64","65+"])
    return b
sv["age_b"] = age_band(sv.age); syn["age_b"] = age_band(syn.age)

# attributes present in BOTH, with friendly labels
ATTRS = [("age_b","Age band"),("gender","Gender"),("employment_status","Employment"),
         ("hhsize","Household size"),("numworkers","Workers"),("numvehicle","Vehicles"),
         ("home_type","Dwelling type"),("home_ownership","Tenure"),("hh_income_detailed","Income bracket")]
ATTRS = [(a,l) for a,l in ATTRS if a in sv.columns and a in syn.columns]

# align encodings: survey stores codes as int64, synth as str -> coerce both to canonical int-string
def norm_col(s):
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().mean() > 0.9:                      # numeric-coded categorical
        return num.round().astype("Int64").astype(str)
    return s.astype(str)
for a,_ in ATTRS:
    sv[a] = norm_col(sv[a]); syn[a] = norm_col(syn[a])

# readable category labels (from pipeline codebook) + canonical ordering
LABELS = {
    "gender": {"1":"Female","2":"Male"},
    "employment_status": {"0":"Worker","1":"Retired","2":"Volunteer","3":"Homemaker",
        "4":"Unemp.(seek)","5":"Unemp.(not)","6":"Student","7":"Disabled","8":"Under-16"},
    "home_type": {"1":"SF detached","2":"SF attached","3":"Apt/Condo","4":"Mobile","5":"Dorm/inst"},
    "home_ownership": {"1":"Own","2":"Rent","3":"Other"},
    "hh_income_detailed": {"1":"<$15k","2":"$15-25k","3":"$25-35k","4":"$35-50k","5":"$50-75k",
        "6":"$75-100k","7":"$100-150k","8":"$150k+"},
}
AGE_ORDER = ["<25","25-34","35-44","45-54","55-64","65+"]
def order_idx(attr, codes):
    codes = set(codes)
    if attr == "age_b": return [c for c in AGE_ORDER if c in codes]
    try: return sorted(codes, key=lambda c: float(c))
    except Exception: return sorted(codes, key=str)
def ticklabels(attr, idx):
    m = LABELS.get(attr, {}); return [m.get(str(v), str(v)) for v in idx]

def wmarg(df, col, wcol=None):
    if wcol: g = df.groupby(col)[wcol].sum()
    else: g = df.groupby(col).size()
    return (g/g.sum())

def tvd(p, q):
    idx = sorted(set(p.index)|set(q.index), key=str)
    p = p.reindex(idx, fill_value=0); q = q.reindex(idx, fill_value=0)
    return 0.5*np.abs(p-q).sum()

def srmse(p, q):
    """Standardized RMSE (Muller & Axhausen): sqrt(mean((p-q)^2)) / mean(p); p,q are
    proportions summing to 1 over C categories, so mean(p)=1/C. 0 = perfect fit."""
    idx = sorted(set(p.index)|set(q.index), key=str)
    p = p.reindex(idx, fill_value=0).values; q = q.reindex(idx, fill_value=0).values
    return float(np.sqrt(np.mean((p-q)**2)) / max(np.mean(p), 1e-12))

# ---------------- FIG 1: population marginals ----------------
n=len(ATTRS); ncol=3; nrow=(n+ncol-1)//ncol
fig, axes = plt.subplots(nrow, ncol, figsize=(12, 3.1*nrow)); axes=axes.ravel()
_M=[]
for ax,(a,lab) in zip(axes, ATTRS):
    sm = wmarg(sv, a, "w"); ym = wmarg(syn, a)
    idx = order_idx(a, set(sm.index)|set(ym.index))
    sm = sm.reindex(idx, fill_value=0)*100; ym = ym.reindex(idx, fill_value=0)*100
    x=np.arange(len(idx))
    ax.bar(x-0.2, sm.values, 0.4, label="survey (weighted)", color=SURVEY, edgecolor="k", lw=0.3)
    ax.bar(x+0.2, ym.values, 0.4, label="synthetic", color=SYNTH, edgecolor="k", lw=0.3)
    ax.set_xticks(x); ax.set_xticklabels(ticklabels(a, idx), fontsize=7.5, rotation=35, ha="right")
    t=tvd(sm/100, ym/100); sr=srmse(sm/100, ym/100); _M.append((lab,t,sr))
    ax.set_title(f"{lab}  (TVD={t:.3f}, SRMSE={sr:.3f})", fontsize=9.5)
    ax.set_ylabel("% of persons", fontsize=8); ax.grid(axis="y", alpha=0.25); ax.tick_params(labelsize=8)
for ax in axes[n:]: ax.axis("off")
h,l = axes[0].get_legend_handles_labels()
fig.legend(h, l, loc="upper center", ncol=2, fontsize=10, frameon=False, bbox_to_anchor=(0.5, 0.965))
_mtvd=np.mean([m[1] for m in _M]); _msr=np.mean([m[2] for m in _M])
fig.suptitle(f"Population synthesis validation: synthetic vs held-out survey TEST split "
             f"(mean TVD={_mtvd:.3f}, mean SRMSE={_msr:.3f})",
             fontsize=12, fontweight="bold", y=1.0)
fig.tight_layout(rect=(0,0,1,0.95))
fig.savefig(OUT/"fig_val_population_marginals.png", dpi=300); fig.savefig(OUT/"fig_val_population_marginals.pdf")
plt.close(fig); print("-> fig_val_population_marginals.png")

# ---------------- FIG 1b: EV owners vs all population (adoption skew) ----------------
ev = pd.read_parquet(INT/"ev_owners.parquet")
ev["age_b"] = age_band(ev.age)
for a,_ in ATTRS:
    if a in ev.columns: ev[a] = norm_col(ev[a])
EVATTRS = [(a,l) for a,l in ATTRS if a in ev.columns]
n=len(EVATTRS); nrow=(n+ncol-1)//ncol
fig, axes = plt.subplots(nrow, ncol, figsize=(12, 3.1*nrow)); axes=axes.ravel()
POP, EVC = pf.GREY, pf.GREEN
for ax,(a,lab) in zip(axes, EVATTRS):
    pm = wmarg(syn, a); em = wmarg(ev, a)
    idx = order_idx(a, set(pm.index)|set(em.index))
    pm = pm.reindex(idx, fill_value=0)*100; em = em.reindex(idx, fill_value=0)*100
    x=np.arange(len(idx))
    ax.bar(x-0.2, pm.values, 0.4, label="all population", color=POP, edgecolor="k", lw=0.3)
    ax.bar(x+0.2, em.values, 0.4, label="EV owners", color=EVC, edgecolor="k", lw=0.3)
    ax.set_xticks(x); ax.set_xticklabels(ticklabels(a, idx), fontsize=7.5, rotation=35, ha="right")
    ax.set_title(lab, fontsize=10)
    ax.set_ylabel("% share", fontsize=8); ax.grid(axis="y", alpha=0.25); ax.tick_params(labelsize=8)
for ax in axes[n:]: ax.axis("off")
h,l = axes[0].get_legend_handles_labels()
fig.legend(h, l, loc="upper center", ncol=2, fontsize=10, frameon=False, bbox_to_anchor=(0.5, 0.965))
fig.suptitle("Who owns EVs: EV owners vs the general synthetic population (adoption skew)",
             fontsize=12.5, fontweight="bold", y=1.0)
fig.tight_layout(rect=(0,0,1,0.95))
fig.savefig(OUT/"fig_val_ev_vs_population.png", dpi=300); fig.savefig(OUT/"fig_val_ev_vs_population.pdf")
plt.close(fig); print("-> fig_val_ev_vs_population.png")

# ---------------- FIG 2: joint associations (Cramer's V) ----------------
from itertools import combinations
def cramers_v(a, b, wv=None):
    ct = pd.crosstab(a, b, values=wv, aggfunc="sum") if wv is not None else pd.crosstab(a,b)
    ct = ct.fillna(0).values
    chi2 = ((ct - ct.sum(1,keepdims=True)*ct.sum(0,keepdims=True)/ct.sum())**2 /
            (ct.sum(1,keepdims=True)*ct.sum(0,keepdims=True)/ct.sum()).clip(1e-9)).sum()
    n=ct.sum(); r,k=ct.shape
    return np.sqrt((chi2/n)/max(1,(min(r,k)-1)))
cats=[a for a,_ in ATTRS]; labs=[l for _,l in ATTRS]
Vs=np.zeros((len(cats),)*2); Vy=np.zeros((len(cats),)*2)
for i,j in combinations(range(len(cats)),2):
    Vs[i,j]=Vs[j,i]=cramers_v(sv[cats[i]], sv[cats[j]], sv.w)
    Vy[i,j]=Vy[j,i]=cramers_v(syn[cats[i]], syn[cats[j]])
np.fill_diagonal(Vs,1); np.fill_diagonal(Vy,1)
fig, ax = plt.subplots(1,3, figsize=(13,4.3))
for a,(M,ttl,cm,vlim) in zip(ax, [(Vs,"(a) Survey (weighted)","viridis",(0,0.6)),
                                   (Vy,"(b) Synthetic","viridis",(0,0.6)),
                                   (Vs-Vy,"(c) Association error (survey − synth)","RdBu_r",(-0.15,0.15))]):
    im=a.imshow(M, cmap=cm, vmin=vlim[0], vmax=vlim[1])
    a.set_xticks(range(len(labs))); a.set_xticklabels(labs, rotation=45, ha="right", fontsize=7.5)
    a.set_yticks(range(len(labs))); a.set_yticklabels(labs, fontsize=7.5)
    a.set_title(ttl, fontsize=10.5)
    fig.colorbar(im, ax=a, fraction=0.046, pad=0.04).ax.tick_params(labelsize=7)
mad=np.abs(Vs-Vy)[np.triu_indices(len(cats),1)].mean()
fig.suptitle(f"Joint associations preserved: Cramer's V matrices (mean abs error = {mad:.3f})",
             fontsize=12.5, fontweight="bold", y=1.01)
fig.tight_layout(rect=(0,0,1,0.98))
fig.savefig(OUT/"fig_val_joint_associations.png", dpi=300); fig.savefig(OUT/"fig_val_joint_associations.pdf")
plt.close(fig); print(f"-> fig_val_joint_associations.png (mean abs Cramer's V error {mad:.3f})")
print(f"\nsurvey TEST n={len(sv):,} (weighted), synth n={len(syn):,}")
