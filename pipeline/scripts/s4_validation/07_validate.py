#!/usr/bin/env python3
"""
07_validate.py — publication-quality validation of the synthetic population, trips
and EV fleet. EVERY metric is written as its OWN figure (separate .pdf + .png via
src.plotstyle.save), so figures drop straight into a paper. Sections:

  A. Population marginals   per-attribute panels + a TVD summary bar
  B. Joint associations     Cramér's V (survey / synth / signed diff, annotated)
  C. County-wise            population vs census, EV owners vs MVA, per-county TVD
  D. Trip fidelity          trips/person, distance, departure hour, daily VMT
  E. EV fleet               ownership income gradient, powertrain split
  F. Model performance      learning curves (train vs val ELBO/rec/KL), overfit gap
  G. Generalisation         held-out TEST fidelity + F(T,S)/F(T,H) ratio
  H. Memorisation / privacy DCR: synth->train vs holdout->train nearest-neighbour

Held-out discipline (deep-research best practice): fidelity is scored on the
TEST split the models never saw; memorisation is checked against an untouched
HOLDOUT. Writes validation_summary.md with every number.
"""
from __future__ import annotations
import sys, glob
from pathlib import Path
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from scipy.stats import chi2_contingency

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
sys.path.insert(0, str(ROOT / "pipeline"))
from src.encoders import DataCodec, age_to_band                        # noqa: E402
from src.cvae import MixedCVAE                                         # noqa: E402
from src.trips import repair_day, SLOT_CAT, SLOT_NUM, COND_CAT, COND_NUM  # noqa: E402
from src import tripdisc                                              # noqa: E402
from src.labels import code_labels                                   # noqa: E402
import json as _json                                                 # noqa: E402
import src.plotstyle as ps                                            # noqa: E402
from src.plotstyle import SURVEY, SYNTH, ACCENT, GREY, save, newfig    # noqa: E402
import matplotlib.pyplot as plt                                       # noqa: E402

INTERIM = ROOT / "pipeline/data/interim"; CKPT = ROOT / "pipeline/checkpoints"
OUT = ROOT / "pipeline/output/validation"; OUT.mkdir(parents=True, exist_ok=True)
# organised output — one folder per validation family
A_DIR = OUT / "A_population_marginals"
B_DIR = OUT / "B_joint_associations"
C_DIR = OUT / "C_countywise"
D_DIR = OUT / "D_trip_marginals"
E_DIR = OUT / "E_ev_fleet"
F_DIR = OUT / "F_model_performance"
G_DIR = OUT / "G_generalisation"
H_DIR = OUT / "H_memorisation"
DEV = "cuda" if torch.cuda.is_available() else "cpu"
LBL = {"home_type": "dwelling type", "hh_income_detailed": "household income",
       "employment_status": "employment", "home_ownership": "tenure",
       "numvehicle": "vehicles", "numworkers": "workers", "numbicycle": "bicycles",
       "home_office": "home office", "charge_at_work": "workplace charging",
       "home_county": "county"}


def tvd(a, b):
    idx = sorted(set(a.index) | set(b.index))
    return 0.5 * float(np.abs(a.reindex(idx, fill_value=0) - b.reindex(idx, fill_value=0)).sum())


def cramers_v(df, cols):
    """Bias-corrected Cramér's V (Bergsma 2013) matrix over `cols`."""
    M = np.eye(len(cols))
    for i, a in enumerate(cols):
        for j, b in enumerate(cols):
            if j <= i:
                continue
            ct = pd.crosstab(df[a], df[b]).to_numpy()
            n = ct.sum()
            if n == 0 or min(ct.shape) < 2:
                v = 0.0
            else:
                chi2 = chi2_contingency(ct, correction=False)[0]
                phi2 = chi2 / n
                r, k = ct.shape
                phi2c = max(0.0, phi2 - (r - 1) * (k - 1) / (n - 1))
                rc = r - (r - 1) ** 2 / (n - 1); kc = k - (k - 1) ** 2 / (n - 1)
                v = np.sqrt(phi2c / max(1e-9, min(rc - 1, kc - 1)))
            M[i, j] = M[j, i] = v
    return M


# ----------------------------------------------------------------------------- helpers
def weighted_marginal(df, col, wcol):
    s = df.groupby(df[col].astype(str))[wcol].sum(); return s / s.sum()


def synth_marginal(df, col):
    return df[col].astype(str).value_counts(normalize=True)


def whist(ax, real, syn_, wr=None, ws=None, bins=40, rng=None, dens=True):
    """Weighted survey vs (unweighted) synth overlaid histogram."""
    ax.hist(real, bins=bins, range=rng, weights=wr, density=dens, alpha=0.55,
            label="survey", color=SURVEY)
    ax.hist(syn_, bins=bins, range=rng, weights=ws, density=dens, alpha=0.55,
            label="synthetic", color=SYNTH)
    ax.set_ylabel("density"); ax.legend()


def num_tvd(real, syn_, wr, bins):
    """TVD between two weighted numeric distributions on a common binning."""
    hr, _ = np.histogram(real, bins=bins, weights=wr, density=True)
    hs, _ = np.histogram(syn_, bins=bins, density=True)
    w = np.diff(bins)
    return 0.5 * float((np.abs(hr - hs) * w).sum())


# =====================================================================================
def main():
    md = ["# Validation summary — UrbanEV-Maryland synthetic population\n"]
    sp = pd.read_parquet(INTERIM / "survey_person.parquet")
    sh = pd.read_parquet(INTERIM / "survey_hh.parquet")
    st = pd.read_parquet(INTERIM / "survey_trip.parquet")
    syn = pd.read_parquet(INTERIM / "synth_person.parquet")
    ev = pd.read_parquet(INTERIM / "ev_owners.parquet")
    surv = sp.merge(sh.drop(columns="wthhfin"), on="household_id", suffixes=("", "_hh"))
    test = surv[surv.split == "test"]          # held-out, never seen by the models
    hold = surv[surv.split == "holdout"]

    ATTRS = ["home_county", "home_type", "home_ownership", "hh_income_detailed", "hhsize",
             "numworkers", "numvehicle", "numbicycle", "gender", "license",
             "employment_status", "home_office", "charge_at_work"]

    # ============================ A. POPULATION MARGINALS ============================
    mdir = A_DIR
    tvds = {}
    for a in ATTRS:
        real = weighted_marginal(surv, a, "wtperfin")
        synm = synth_marginal(syn, a)
        tvds[a] = tvd(real, synm)
        order = sorted(set(real.index) | set(synm.index), key=lambda x: (len(str(x)), str(x)))
        if a == "home_county":
            order = list(real.sort_values(ascending=False).index)[:24]
        x = np.arange(len(order))
        labs = code_labels(a, order)
        long = max((len(str(t)) for t in labs), default=1) > 3
        fig, ax = newfig(max(5.2, (0.42 if long else 0.32) * len(order)), 3.9 if long else 3.6)
        ax.bar(x - .2, real.reindex(order, fill_value=0), .4, label="survey (weighted)", color=SURVEY)
        ax.bar(x + .2, synm.reindex(order, fill_value=0), .4, label="synthetic", color=SYNTH)
        ax.set_xticks(x)
        ax.set_xticklabels(labs, rotation=(40 if long else 0), ha=("right" if long else "center"),
                           fontsize=8)
        ax.set_ylabel("share"); ax.set_title(f"{LBL.get(a, a)}  (TVD = {tvds[a]:.3f})")
        ax.legend()
        save(fig, mdir, f"marginal_{a}")

    # age (numeric) marginal
    ages = pd.to_numeric(surv.age, errors="coerce"); ok = ages.notna()
    syn_age = pd.to_numeric(syn.age, errors="coerce").dropna()
    abins = np.arange(0, 101, 5)
    age_tvd = num_tvd(ages[ok], syn_age, surv.wtperfin[ok].to_numpy(), abins)
    tvds["age"] = age_tvd
    fig, ax = newfig(5.2, 3.6)
    whist(ax, ages[ok], syn_age, wr=surv.wtperfin[ok].to_numpy(), bins=abins)
    ax.set_xlabel("age (years)")
    ax.set_title(f"Age  (TVD = {age_tvd:.3f}; mean survey "
                 f"{np.average(ages[ok], weights=surv.wtperfin[ok]):.1f} / synth {syn_age.mean():.1f})")
    save(fig, mdir, "marginal_age")

    # ADULT age 16+ — the driving/EV-relevant population (children aren't agents and are
    # a VAE minority mode the model under-generates; the whole-pop age gap is all <16).
    am = ok & (ages >= 16); sa = syn_age[syn_age >= 16]; ab2 = np.arange(16, 101, 5)
    adult_tvd = num_tvd(ages[am], sa, surv.wtperfin[am].to_numpy(), ab2)
    tvds["age_16plus"] = adult_tvd
    fig, ax = newfig(5.2, 3.6)
    whist(ax, ages[am], sa, wr=surv.wtperfin[am].to_numpy(), bins=ab2)
    ax.set_xlabel("age (years)")
    ax.set_title(f"Age 16+ (driving-age)  (TVD = {adult_tvd:.3f}; mean survey "
                 f"{np.average(ages[am], weights=surv.wtperfin[am]):.1f} / synth {sa.mean():.1f})")
    save(fig, mdir, "marginal_age_16plus")

    # age at the MODEL'S BAND resolution (categorical age_band output, not a density)
    sab = age_to_band(surv.age[ok]); syab = age_to_band(syn.age)
    NB = int(max(sab.max(), syab.max())) + 1
    rr = np.bincount(sab[sab >= 0], weights=surv.wtperfin[ok].to_numpy()[sab >= 0], minlength=NB); rr = rr / rr.sum()
    ss = np.bincount(syab[syab >= 0], minlength=NB); ss = ss / ss.sum()
    tvds["age_bands"] = 0.5 * float(np.abs(rr - ss).sum())
    fig, ax = newfig(6.2, 3.8); x = np.arange(NB)
    ax.bar(x - .2, rr, .4, label="survey (weighted)", color=SURVEY)
    ax.bar(x + .2, ss, .4, label="synthetic", color=SYNTH)
    ax.set_xticks(x); ax.set_xticklabels(code_labels("age_band", range(NB)), rotation=40, ha="right", fontsize=8)
    ax.set_ylabel("share"); ax.set_title(f"Age — model bands  (band TVD = {tvds['age_bands']:.3f})")
    ax.legend(); save(fig, mdir, "marginal_age_bands")

    # summary TVD bar (paper-ready single figure)
    order = sorted(tvds, key=tvds.get)
    fig, ax = newfig(6.4, 3.8)
    cols = [ACCENT if tvds[a] < 0.05 else (SYNTH if tvds[a] < 0.1 else "#D55E00") for a in order]
    ax.barh([LBL.get(a, a) for a in order], [tvds[a] for a in order], color=cols)
    ax.axvline(0.05, color=GREY, ls="--", lw=0.8)
    ax.set_xlabel("total variation distance (synthetic vs survey-weighted)")
    ax.set_title("Population marginal fidelity")
    save(fig, A_DIR, "fig_A_marginal_tvd")
    md += ["## A. Population marginals (synth vs survey-weighted)\n",
           "| attribute | TVD |\n|---|---|"]
    md += [f"| {a} | {tvds[a]:.3f} |" for a in order]
    md += [f"\n**mean TVD = {np.mean(list(tvds.values())):.3f}**, "
           f"max = {max(tvds.values()):.3f} ({max(tvds, key=tvds.get)})\n"]

    # ============================ B. CRAMÉR'S V JOINTS ==============================
    cc = ["home_type", "home_ownership", "hh_income_detailed", "hhsize", "numworkers",
          "numvehicle", "numbicycle", "license", "employment_status", "home_office"]
    lab = [LBL.get(c, c) for c in cc]
    Vs = cramers_v(surv.astype({c: str for c in cc}), cc)
    syn_s = syn.sample(min(200_000, len(syn)), random_state=1).astype({c: str for c in cc})
    Vy = cramers_v(syn_s, cc)
    diff = Vs - Vy                                        # signed: +ve = synth under-associates

    def heat(M, name, title, diverging=False):
        fig, ax = newfig(5.6, 5.0)
        if diverging:
            vmax = float(np.abs(M[~np.eye(len(cc), dtype=bool)]).max()); vmax = max(vmax, 0.02)
            im = ax.imshow(M, cmap="RdBu_r", vmin=-vmax, vmax=vmax)
        else:
            im = ax.imshow(M, cmap="cividis", vmin=0, vmax=1)
        ax.set_xticks(range(len(cc))); ax.set_xticklabels(lab, rotation=90, fontsize=8)
        ax.set_yticks(range(len(cc))); ax.set_yticklabels(lab, fontsize=8)
        thr = (vmax if diverging else 1.0)
        for i in range(len(cc)):
            for j in range(len(cc)):
                if diverging and i == j:
                    continue
                val = M[i, j]
                tc = "white" if (not diverging and val > 0.55) or (diverging and abs(val) > 0.6 * thr) else "black"
                ax.text(j, i, f"{val:.2f}", ha="center", va="center", fontsize=6, color=tc)
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cb.set_label("Δ Cramér's V (survey − synth)" if diverging else "Cramér's V")
        ax.set_title(title); ax.grid(False)
        save(fig, B_DIR, name)

    heat(Vs, "fig_B_cramersv_survey", "Categorical associations — survey")
    heat(Vy, "fig_B_cramersv_synth", "Categorical associations — synthetic")
    heat(diff, "fig_B_cramersv_diff", "Association error (survey − synthetic)", diverging=True)
    offdiag = ~np.eye(len(cc), dtype=bool)
    md += ["## B. Joint associations (bias-corrected Cramér's V)\n",
           f"mean |Δ| = {np.abs(diff[offdiag]).mean():.3f}, "
           f"max |Δ| = {np.abs(diff[offdiag]).max():.3f}\n"]

    # ---- B2: pairwise 2-D JOINT fidelity (TVD of every categorical pair) ----------
    jvars = ["home_county", "home_type", "home_ownership", "hh_income_detailed", "hhsize",
             "numworkers", "numvehicle", "numbicycle", "gender", "license",
             "employment_status", "home_office", "charge_at_work"]
    jlab = [LBL.get(v, v) for v in jvars]

    def joint(df, a, b, wcol=None):
        if wcol:
            ct = pd.crosstab(df[a].astype(str), df[b].astype(str),
                             values=df[wcol], aggfunc="sum")
        else:
            ct = pd.crosstab(df[a].astype(str), df[b].astype(str))
        ct = ct.fillna(0)
        return ct / ct.to_numpy().sum()

    JT = np.zeros((len(jvars), len(jvars)))
    for i, a in enumerate(jvars):
        for j, b in enumerate(jvars):
            if j <= i:
                continue
            ja = joint(surv, a, b, "wtperfin"); js = joint(syn, a, b)
            ix = sorted(set(ja.index) | set(js.index)); cx = sorted(set(ja.columns) | set(js.columns))
            ja = ja.reindex(index=ix, columns=cx, fill_value=0)
            js = js.reindex(index=ix, columns=cx, fill_value=0)
            JT[i, j] = JT[j, i] = 0.5 * float(np.abs(ja.to_numpy() - js.to_numpy()).sum())
    fig, ax = newfig(6.4, 5.8)
    im = ax.imshow(JT, cmap="cividis", vmin=0, vmax=max(0.1, JT.max()))
    ax.set_xticks(range(len(jvars))); ax.set_xticklabels(jlab, rotation=90, fontsize=7)
    ax.set_yticks(range(len(jvars))); ax.set_yticklabels(jlab, fontsize=7)
    for i in range(len(jvars)):
        for j in range(len(jvars)):
            if i != j:
                ax.text(j, i, f"{JT[i,j]:.2f}", ha="center", va="center", fontsize=5.5,
                        color="white" if JT[i, j] > 0.55 * JT.max() else "black")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04); cb.set_label("joint TVD (survey − synth)")
    ax.set_title("Pairwise 2-D joint fidelity (all pairs)"); ax.grid(False)
    save(fig, B_DIR, "fig_B_joint_tvd_matrix")

    # ---- B3: detailed 2-D joint distributions for notable / policy pairs ----------
    jdir = B_DIR / "joints"
    PAIRS = [("hh_income_detailed", "numvehicle"), ("hh_income_detailed", "home_type"),
             ("home_county", "hh_income_detailed"), ("hhsize", "numvehicle"),
             ("employment_status", "license"), ("numworkers", "numvehicle"),
             ("hh_income_detailed", "employment_status"), ("license", "numvehicle")]
    for a, b in PAIRS:
        ja = joint(surv, a, b, "wtperfin"); js = joint(syn, a, b)
        ix = sorted(set(ja.index) | set(js.index), key=lambda x: (len(x), x))
        cx = sorted(set(ja.columns) | set(js.columns), key=lambda x: (len(x), x))
        ja = ja.reindex(index=ix, columns=cx, fill_value=0).to_numpy()
        js = js.reindex(index=ix, columns=cx, fill_value=0).to_numpy()
        d2 = js - ja                                     # synth − survey
        vmax = max(0.01, np.abs(d2).max())
        fig, ax = newfig(max(4.6, 0.5 * len(cx) + 2), max(4.0, 0.4 * len(ix) + 1.5))
        im = ax.imshow(d2, cmap="RdBu_r", vmin=-vmax, vmax=vmax, aspect="auto")
        ax.set_xticks(range(len(cx))); ax.set_xticklabels(cx, rotation=90, fontsize=7)
        ax.set_yticks(range(len(ix))); ax.set_yticklabels(ix, fontsize=7)
        ax.set_xlabel(LBL.get(b, b)); ax.set_ylabel(LBL.get(a, a))
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04); cb.set_label("P(synth) − P(survey)")
        ax.set_title(f"{LBL.get(a,a)} × {LBL.get(b,b)}  (joint TVD = {0.5*np.abs(d2).sum():.3f})")
        ax.grid(False)
        save(fig, jdir, f"joint_{a}__{b}")
    jt_off = JT[~np.eye(len(jvars), dtype=bool)]
    md += ["## B2. Pairwise 2-D joint fidelity\n",
           f"mean joint TVD = {jt_off.mean():.3f}, max = {jt_off.max():.3f} "
           f"({jlab[divmod(int(np.argmax(JT)), len(jvars))[0]]} × "
           f"{jlab[divmod(int(np.argmax(JT)), len(jvars))[1]]})\n"]

    # ============================ C. COUNTY-WISE ===================================
    census = pd.read_csv(ROOT / "pipeline/data/geo/md_county_pop.csv",
                         dtype={"fips": str}).set_index("fips")["pop"]
    d = pd.read_csv(glob.glob(str(ROOT / "Upstream/EV Assignment Model/Input/MDOT_MVA*.csv"))[0])
    d.columns = [c.strip() for c in d.columns]; mm = d[d.Year_Month == "2026/01"].copy()
    mm["Count"] = pd.to_numeric(mm.Count.astype(str).str.replace(",", ""), errors="coerce")
    MDN = {"ALLEGANY": "24001", "ANNE ARUNDEL": "24003", "BALTIMORE": "24005", "CALVERT": "24009",
           "CAROLINE": "24011", "CARROLL": "24013", "CECIL": "24015", "CHARLES": "24017",
           "DORCHESTER": "24019", "FREDERICK": "24021", "GARRETT": "24023", "HARFORD": "24025",
           "HOWARD": "24027", "KENT": "24029", "MONTGOMERY": "24031", "PRINCE GEORGES": "24033",
           "QUEEN ANNES": "24035", "SAINT MARYS": "24037", "SOMERSET": "24039", "TALBOT": "24041",
           "WASHINGTON": "24043", "WICOMICO": "24045", "WORCESTER": "24047", "BALTIMORE CITY": "24510"}
    mm["fips"] = mm.County.astype(str).str.upper().str.strip().map(MDN)
    mva = mm.dropna(subset=["fips"]).groupby("fips").Count.sum()
    synpop = syn.home_county.value_counts(); synev = ev.home_county.value_counts()

    def scatter45(real, got, name, title, unit):
        idx = sorted(set(real.index) & set(got.index))
        rv = real.reindex(idx).to_numpy(float); gv = got.reindex(idx).to_numpy(float)
        r = np.corrcoef(rv, gv)[0, 1]
        fig, ax = newfig(4.8, 4.6)
        ax.scatter(rv, gv, s=34, color=SYNTH, edgecolor="k", linewidth=0.4, zorder=3)
        lim = [min(rv.min(), gv.min()) * 0.8, max(rv.max(), gv.max()) * 1.2]
        ax.plot(lim, lim, ls="--", color=GREY, lw=1, zorder=1)
        ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlim(lim); ax.set_ylim(lim)
        ax.set_xlabel(f"official {unit}"); ax.set_ylabel(f"synthetic {unit}")
        ax.set_title(f"{title}\n(r = {r:.4f}, n = {len(idx)} counties)")
        save(fig, C_DIR, name)
        return r

    r_pop = scatter45(census, synpop, "fig_C_county_population", "County population vs Census", "persons")
    r_ev = scatter45(mva, synev, "fig_C_county_ev", "County EV owners vs MVA", "EV registrations")

    # per-county income-distribution TVD (fidelity beyond totals)
    ctvd = {}
    for c, g in surv.groupby("home_county"):
        sg = syn[syn.home_county == c]
        if len(g) < 30 or len(sg) == 0:
            continue
        rr = weighted_marginal(g, "hh_income_detailed", "wtperfin")
        ss = synth_marginal(sg, "hh_income_detailed")
        ctvd[c] = tvd(rr, ss)
    cser = pd.Series(ctvd).sort_values()
    fig, ax = newfig(6.6, 5.2)
    ax.barh(code_labels("home_county", cser.index), cser.values, color=SYNTH)
    ax.axvline(np.mean(list(ctvd.values())), color=GREY, ls="--", lw=0.8,
               label=f"mean {np.mean(list(ctvd.values())):.3f}")
    ax.set_xlabel("income-distribution TVD (synth vs survey)")
    ax.set_title("Per-county income fidelity"); ax.legend()
    save(fig, C_DIR, "fig_C_county_income_tvd")
    # ---- C2: county × attribute TVD heatmap (ALL attributes, every county) --------
    NM = {  # fips -> short county name (for readable rows)
        "24001": "Allegany", "24003": "Anne Arundel", "24005": "Baltimore Co",
        "24009": "Calvert", "24011": "Caroline", "24013": "Carroll", "24015": "Cecil",
        "24017": "Charles", "24019": "Dorchester", "24021": "Frederick", "24023": "Garrett",
        "24025": "Harford", "24027": "Howard", "24029": "Kent", "24031": "Montgomery",
        "24033": "Prince George's", "24035": "Queen Anne's", "24037": "St Mary's",
        "24039": "Somerset", "24041": "Talbot", "24043": "Washington", "24045": "Wicomico",
        "24047": "Worcester", "24510": "Baltimore City"}
    cattr = [a for a in ATTRS if a != "home_county"] + ["age"]
    counties = [c for c in census.index if (surv.home_county == c).sum() >= 30]
    counties = sorted(counties, key=lambda c: -census.get(c, 0))
    CT = np.full((len(counties), len(cattr)), np.nan)
    for ci, c in enumerate(counties):
        g = surv[surv.home_county == c]; sg = syn[syn.home_county == c]
        if len(sg) == 0:
            continue
        for ai, a in enumerate(cattr):
            if a == "age":
                gg = pd.to_numeric(g.age, errors="coerce"); m = gg.notna()
                CT[ci, ai] = num_tvd(gg[m], pd.to_numeric(sg.age, errors="coerce").dropna(),
                                     g.wtperfin[m].to_numpy(), np.arange(0, 101, 5))
            else:
                CT[ci, ai] = tvd(weighted_marginal(g, a, "wtperfin"), synth_marginal(sg, a))
    fig, ax = newfig(max(7, 0.55 * len(cattr) + 2), max(6, 0.34 * len(counties) + 1.5))
    im = ax.imshow(CT, cmap="cividis", vmin=0, vmax=min(0.4, np.nanmax(CT)), aspect="auto")
    ax.set_xticks(range(len(cattr))); ax.set_xticklabels([LBL.get(a, a) for a in cattr], rotation=90, fontsize=8)
    ax.set_yticks(range(len(counties))); ax.set_yticklabels([NM.get(c, c) for c in counties], fontsize=7)
    for ci in range(len(counties)):
        for ai in range(len(cattr)):
            if np.isfinite(CT[ci, ai]):
                ax.text(ai, ci, f"{CT[ci,ai]:.2f}", ha="center", va="center", fontsize=5,
                        color="white" if CT[ci, ai] > 0.22 else "black")
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.03); cb.set_label("TVD (synth vs survey-weighted)")
    ax.set_title("County × attribute marginal fidelity"); ax.grid(False)
    save(fig, C_DIR, "fig_C_county_attribute_tvd")

    # ---- C3: per-county marginal panels for key attributes (one file per county) --
    key_attrs = ["hh_income_detailed", "hhsize", "numvehicle", "employment_status"]
    cdir = C_DIR / "per_county"
    for c in counties:
        g = surv[surv.home_county == c]; sg = syn[syn.home_county == c]
        fig, axes = plt.subplots(2, 2, figsize=(9, 6.4))
        for a, axk in zip(key_attrs, axes.ravel()):
            rr = weighted_marginal(g, a, "wtperfin"); ss = synth_marginal(sg, a)
            order = sorted(set(rr.index) | set(ss.index), key=lambda x: (len(str(x)), str(x)))
            xx = np.arange(len(order))
            axk.bar(xx - .2, [rr.get(o, 0) for o in order], .4, color=SURVEY, label="survey")
            axk.bar(xx + .2, [ss.get(o, 0) for o in order], .4, color=SYNTH, label="synth")
            axk.set_xticks(xx); axk.set_xticklabels(code_labels(a, order), fontsize=7,
                                                    rotation=40, ha="right")
            axk.set_title(f"{LBL.get(a, a)} (TVD={tvd(rr, ss):.3f})", fontsize=10)
        axes[0, 0].legend(fontsize=8)
        fig.suptitle(f"{NM.get(c, c)} ({c}) — n_survey={len(g)}, n_synth={len(sg):,}", fontsize=12)
        save(fig, cdir, f"county_{c}_{NM.get(c, c).replace(' ', '').replace(chr(39), '')}")

    cmean = np.nanmean(CT); cmax_ij = np.unravel_index(np.nanargmax(CT), CT.shape)
    md += ["## C. County-wise\n",
           f"population vs census: r = {r_pop:.4f}; EV owners vs MVA: r = {r_ev:.4f}",
           f"per-county income TVD: mean {np.mean(list(ctvd.values())):.3f}, "
           f"worst {NM.get(cser.index[-1], cser.index[-1])} = {cser.iloc[-1]:.3f}",
           f"county×attribute TVD: mean {cmean:.3f}, worst = "
           f"{NM.get(counties[cmax_ij[0]], counties[cmax_ij[0]])} / {cattr[cmax_ij[1]]} "
           f"= {CT[cmax_ij]:.3f}",
           f"(per-county panels for {len(counties)} counties in C_countywise/per_county/)\n"]

    # ============================ D. TRIP FIDELITY =================================
    # Production trip model = FULLY CATEGORICAL discretized-magnitude CVAE (02e): its
    # softmax magnitude bands reproduce the heavy distance tail a Gaussian head washes
    # out (distance TVD 0.11 -> 0.015, VMT gap -8% -> -5% vs the weighted survey).
    tck = torch.load(CKPT / "trip_disc_cvae.pt", map_location=DEV, weights_only=False)
    tmodel = MixedCVAE(tck["cat_cards"], tck["num_fields"], tck["latent"], tck["hidden"],
                       tck["cond_dim"], dropout=tck.get("dropout", 0.0))
    tmodel.load_state_dict(tck["state_dict"]); tmodel.to(DEV).eval()
    tcodec = DataCodec.load(CKPT / "trip_disc_codec.json"); ccodec = DataCodec.load(CKPT / "cond_codec.json")
    edges = _json.load(open(CKPT / "mag_edges.json")); rng_d = np.random.default_rng(2)
    samp_p = syn.sample(80_000, random_state=2).copy()
    for c in ["hhsize", "numworkers", "numvehicle", "age"]:
        samp_p[c] = pd.to_numeric(samp_p[c], errors="coerce").fillna(0)
    idx = ccodec.encode(samp_p, device=DEV)
    cond = torch.cat([F.one_hot(idx[f], ccodec.cardinalities()[f]).float() for f in COND_CAT]
                     + [idx[f].unsqueeze(-1) for f in COND_NUM], dim=-1)
    # forbid the PAD placeholder on real slots (kchain sets the length, so PAD is never
    # needed): mode "0" and magnitude band "-1" otherwise leaked into ~5% of occupied
    # trips as invalid mode-0 / clipped-to-band-0 spikes.
    def _pad_idx(field, padval):
        c = tcodec.cats.get(field, []); return [c.index(padval)] if padval in c else []
    forbid = {}
    for j in range(tripdisc.K_MAX):
        forbid[f"mode_{j}"] = _pad_idx(f"mode_{j}", "0")
        forbid[f"act_{j}"] = _pad_idx(f"act_{j}", "0")
        forbid[f"depb_{j}"] = _pad_idx(f"depb_{j}", "-1")
        for mg in ("logdistb", "travelb"):
            forbid[f"{mg}_{j}"] = _pad_idx(f"{mg}_{j}", "-1")
    s = tmodel.sample(len(samp_p), cond=cond, device=DEV, forbid=forbid)
    dec = {f: tcodec.decode_cat(f, s[f]) for f in tripdisc.SLOT_CAT}
    ntr, vmt, deph = [], [], []
    dists, modes, acts, dwells, travs, allhr = [], [], [], [], [], []
    for i in range(len(samp_p)):
        ch = tripdisc.repair_disc(dec, i, edges, rng_d)
        ntr.append(len(ch)); vmt.append(sum(c["distance"] for c in ch))
        if ch:
            deph.append(ch[0]["dep_min"] / 60)
            for j, c in enumerate(ch):
                dists.append(c["distance"]); modes.append(c["mode"]); acts.append(c["activity"])
                travs.append(c["arr_min"] - c["dep_min"]); allhr.append(c["dep_min"] / 60)
                if j < len(ch) - 1:               # exclude the final home leg (overnight
                    dwells.append(c["dwell_min"])  # dwell is the end-of-day anchor, not a stop)
    # WEIGHTED survey references (representative population — synth matches census, not
    # the raw survey): weight per-person trips/VMT by wtperfin, marginals by wttrdfin.
    rn = st.groupby("person_id").size(); rvmt = st.groupby("person_id").distance.sum()
    pw = sp.set_index("person_id").wtperfin.reindex(rn.index).fillna(1.0).to_numpy()
    rn_w = float(np.average(rn, weights=pw)); rvmt_w = float(np.average(rvmt, weights=pw))
    wtr = st.wttrdfin.to_numpy()               # trip expansion weight (survey marginals)

    def twohist(real, syn_, name, title, xlabel, bins, rng=None, dens=True, vlines=None):
        fig, ax = newfig(5.2, 3.6)
        ax.hist(real, bins=bins, range=rng, density=dens, alpha=0.55, label="survey", color=SURVEY)
        ax.hist(syn_, bins=bins, range=rng, density=dens, alpha=0.55, label="synthetic", color=SYNTH)
        for v, lb in (vlines or []):
            ax.axvline(v, color=ACCENT, ls="--", lw=1, label=lb)
        ax.set_xlabel(xlabel); ax.set_ylabel("density"); ax.set_title(title); ax.legend()
        save(fig, D_DIR, name)

    tdir = D_DIR
    twohist(rn, ntr, "trip_trips_per_person",
            f"Trips per person (survey {rn.mean():.2f} / synth {np.mean(ntr):.2f})",
            "trips per person", bins=range(0, 15))
    # per-trip attribute marginals (survey weighted by trip weight) --------------
    def trip_cat(col_survey, syn_list, name, title, xlabel):
        rr = st.groupby(st[col_survey].astype(int)).wttrdfin.sum(); rr = rr / rr.sum()
        ss = pd.Series([int(v) for v in syn_list]).value_counts(normalize=True)
        t = tvd(rr.rename(index=str), ss.rename(index=str))
        order = sorted(set(rr.index) | set(ss.index))
        x = np.arange(len(order))
        fig, ax = newfig(max(5.6, 0.5 * len(order)), 3.9)
        ax.bar(x - .2, [rr.get(o, 0) for o in order], .4, label="survey (weighted)", color=SURVEY)
        ax.bar(x + .2, [ss.get(o, 0) for o in order], .4, label="synthetic", color=SYNTH)
        ax.set_xticks(x)
        ax.set_xticklabels(code_labels(col_survey, order), rotation=40, ha="right", fontsize=8)
        ax.set_ylabel("share"); ax.set_title(f"{title}  (TVD = {t:.3f})"); ax.legend()
        save(fig, tdir, name); return t

    # survey INTERIOR trips (exclude each person's last/home leg — its dwell is the
    # overnight anchor, not a comparable stop) for the dwell marginal
    st_sorted = st.sort_values(["person_id", "tripno"])
    last_idx = st_sorted.groupby("person_id").tail(1).index
    st_int = st.drop(last_idx)

    def trip_num(col_survey, syn_list, name, title, xlabel, hi, bins=40, survey=None):
        sdf = st if survey is None else survey
        rvals = np.clip(pd.to_numeric(sdf[col_survey], errors="coerce"), 0, hi)
        wv = sdf.wttrdfin.to_numpy()
        svals = np.clip(np.array(syn_list), 0, hi)
        bb = np.linspace(0, hi, bins + 1)
        t = num_tvd(rvals, svals, wv, bb)
        fig, ax = newfig(5.2, 3.6)
        whist(ax, rvals, svals, wr=wv, bins=bb)
        ax.set_xlabel(xlabel)
        ax.set_title(f"{title}  (TVD = {t:.3f}; mean survey "
                     f"{np.average(rvals, weights=wv):.1f} / synth {np.mean(svals):.1f})")
        save(fig, tdir, name); return t

    ttv = {}
    ttv["trips_per_person"] = num_tvd(rn, np.array(ntr), pw, np.arange(0, 15))
    ttv["destination_activity"] = trip_cat("d_activity", acts, "trip_activity",
                                           "Destination activity / purpose", "activity code")
    ttv["travel_mode"] = trip_cat("travel_mode", modes, "trip_mode", "Travel mode", "mode code")
    ttv["distance"] = trip_num("distance", dists, "trip_distance", "Trip distance", "distance (mi)", 50)
    ttv["travel_time"] = trip_num("travel_min", travs, "trip_travel_time", "Trip travel time",
                                  "travel time (min)", 120)
    ttv["dwell_time"] = trip_num("dwell_min", dwells, "trip_dwell_time",
                                 "Activity dwell time (interior stops)", "dwell (min)", 600,
                                 survey=st_int)

    # ---- BAND-LEVEL validation: the model outputs CATEGORICAL log-bands, so compare
    # survey vs synth at that native resolution (bin both to the model's edges). This
    # removes the within-bin decode + survey digit-heaping that inflate the density-
    # histogram TVDs above, showing what the softmax bands actually reproduce. ----
    NB = tripdisc.N_MAG_BINS

    def trip_band(col_survey, syn_vals, m, name, title, survey=None):
        e = np.array(edges[m]); sdf = st if survey is None else survey
        def to_band(v):
            lv = np.log1p(np.clip(pd.to_numeric(pd.Series(list(v)), errors="coerce")
                                  .fillna(0).to_numpy(), 0, None))
            return np.clip(np.digitize(lv, e[1:-1]), 0, NB - 1)
        rb, wv = to_band(sdf[col_survey]), sdf.wttrdfin.to_numpy()
        rr = np.bincount(rb, weights=wv, minlength=NB); rr = rr / rr.sum()
        sb = to_band(syn_vals); ss = np.bincount(sb, minlength=NB); ss = ss / ss.sum()
        t = 0.5 * float(np.abs(rr - ss).sum())
        fig, ax = newfig(6.2, 3.4); x = np.arange(NB)
        ax.bar(x - .2, rr, .4, label="survey (weighted)", color=SURVEY)
        ax.bar(x + .2, ss, .4, label="synthetic", color=SYNTH)
        ax.set_xlabel(f"log-distance band (0..{NB-1})" if m == "logdist" else f"log-{m} band (0..{NB-1})")
        ax.set_ylabel("share"); ax.set_title(f"{title} — model bands  (band TVD = {t:.3f})"); ax.legend()
        save(fig, tdir, name); return t

    ttv["distance_bands"] = trip_band("distance", dists, "logdist", "trip_distance_bands", "Trip distance")
    ttv["travel_time_bands"] = trip_band("travel_min", travs, "travel", "trip_travel_time_bands", "Travel time")
    # all-trip departure hour (weighted survey)
    bb = np.arange(0, 25); ttv["departure_hour"] = num_tvd(st.dep_min / 60, np.array(allhr), wtr, bb)
    fig, ax = newfig(5.4, 3.6)
    whist(ax, st.dep_min / 60, np.array(allhr), wr=wtr, bins=bb)
    ax.set_xlabel("hour of day"); ax.set_title(f"Departure hour (all trips)  (TVD = {ttv['departure_hour']:.3f})")
    save(fig, tdir, "trip_departure_hour_all")
    # first departure + daily VMT (top-level, retained)
    # survey FIRST departure per person (previously compared against ALL survey trips,
    # which peak in the PM — that made the correctly AM-peaked synth look wrong)
    sfd = (st.sort_values(["person_id", "tripno"]).groupby("person_id").dep_min.first()) / 60
    sfw = sp.set_index("person_id").wtperfin.reindex(sfd.index).fillna(1.0).to_numpy()
    ttv["first_departure"] = num_tvd(sfd, np.array(deph), sfw, np.arange(0, 25))
    fig, ax = newfig(5.4, 3.6)
    whist(ax, sfd, np.array(deph), wr=sfw, bins=np.arange(0, 25))
    ax.set_xlabel("hour of day")
    ax.set_title(f"First departure hour  (TVD = {ttv['first_departure']:.3f})")
    save(fig, tdir, "fig_D_departure_hour")
    twohist(np.clip(rvmt, 0, 120), np.clip(vmt, 0, 120), "fig_D_daily_vmt",
            f"Daily VMT (survey-wt {rvmt_w:.1f} / synth {np.mean(vmt):.1f} mi)",
            "daily VMT (mi)", bins=40, vlines=[(29.4, "~10.7k mi/yr real-EV")])

    md += ["## D. Trip fidelity (fully-categorical discretized model; 100% feasible)\n",
           "| trip variable | TVD |\n|---|---|"]
    md += [f"| {k} | {v:.3f} |" for k, v in sorted(ttv.items(), key=lambda kv: kv[1])]
    md += [f"\ntrips/person: **weighted** survey {rn_w:.2f} vs synth {np.mean(ntr):.2f}; "
           f"daily VMT/person weighted survey {rvmt_w:.1f} vs synth {np.mean(vmt):.1f} mi "
           f"({100*(np.mean(vmt)-rvmt_w)/rvmt_w:+.1f}%; per-trip {rvmt_w/rn_w:.2f} vs "
           f"{np.mean(vmt)/max(1e-9,np.mean(ntr)):.2f} mi)\n"]

    # ============================ E. EV FLEET ======================================
    ev["inc"] = pd.to_numeric(ev.hh_income_detailed, errors="coerce")
    cand = syn[(pd.to_numeric(syn.age) >= 16) & (syn.license.astype(str) == "1")].copy()
    cand["inc"] = pd.to_numeric(cand.hh_income_detailed, errors="coerce")
    rate = (ev.groupby("inc").size() / cand.groupby("inc").size()).dropna()
    fig, ax = newfig(5.2, 3.6)
    ax.bar(rate.index, rate.values * 100, color=ACCENT)
    ax.set_xlabel("household income category (1 = lowest → 8 = highest)")
    ax.set_ylabel("EV ownership rate (%)"); ax.set_title("EV ownership by income (Lavan–Cirillo)")
    save(fig, E_DIR, "fig_E_income_gradient")
    fig, ax = newfig(3.8, 3.6)
    shares = [(ev.ev_powertrain == "BEV").mean(), (ev.ev_powertrain == "PHEV").mean()]
    ax.bar(["BEV", "PHEV"], [x * 100 for x in shares], color=[SURVEY, SYNTH])
    ax.axhline(73.8, color=GREY, ls="--", lw=1, label="MVA BEV 73.8%")
    ax.set_ylabel("share (%)"); ax.set_title("Powertrain split"); ax.legend()
    save(fig, E_DIR, "fig_E_powertrain")
    md += ["## E. EV fleet\n",
           f"total EV agents {len(ev):,}; BEV {shares[0]*100:.1f}% (MVA 73.8%); "
           f"ownership rises {rate.iloc[0]*100:.2f}% → {rate.iloc[-1]*100:.2f}% across income\n"]

    # ============================ F. MODEL PERFORMANCE =============================
    for tag, ck, nm in [("population", torch.load(CKPT / "population_cvae.pt", map_location="cpu", weights_only=False), "Population VAE"),
                        ("trip", tck, "Trip CVAE")]:
        h = ck["history"]; epx = h["epoch"]
        fig, ax = newfig(5.4, 3.6)
        ax.plot(epx, h["tr_loss"], color=SURVEY, label="train ELBO")
        ax.plot(epx, h["va_loss"], color=SYNTH, label="validation ELBO")
        best = int(np.nanargmin(h["va_loss"]))
        ax.axvline(best, color=ACCENT, ls="--", lw=1, label=f"best/early-stop (ep {epx[best]})")
        ax.set_xlabel("epoch"); ax.set_ylabel("weighted ELBO (−)"); ax.set_title(f"{nm} — learning curve")
        ax.legend()
        save(fig, F_DIR, f"fig_F_learning_{tag}")
        # overfitting gap + rec/kl decomposition
        fig, ax = newfig(5.4, 3.6)
        gap = np.array(h["va_loss"]) - np.array(h["tr_loss"])
        ax.plot(epx, gap, color="#D55E00", label="val − train ELBO (overfit gap)")
        ax.plot(epx, h["tr_rec"], color=SURVEY, lw=1, alpha=.7, label="train recon")
        ax.plot(epx, h["tr_kl"], color=GREY, lw=1, alpha=.9, label="train KL")
        ax.set_xlabel("epoch"); ax.set_ylabel("nats"); ax.set_title(f"{nm} — generalisation gap & ELBO terms")
        ax.legend()
        save(fig, F_DIR, f"fig_F_overfit_{tag}")
        md += [f"## F. {nm} training\nbest val ELBO {np.nanmin(h['va_loss']):.3f} at epoch {epx[best]}; "
               f"final overfit gap {gap[-1]:.3f}\n"]

    # ============================ G. HELD-OUT GENERALISATION =======================
    # F(T,S)/F(T,H): compare synth->test fidelity to holdout->test (train-analog). ~1 = good.
    md += ["## G. Held-out generalisation (TEST split, never trained on)\n",
           "| attribute | TVD(synth,TEST) | TVD(TRAIN,TEST) | ratio |\n|---|---|---|---|"]
    tr_df = surv[surv.split == "train"]
    ratios = []
    for a in ATTRS:
        te = weighted_marginal(test, a, "wtperfin")
        sy = synth_marginal(syn, a)
        trm = weighted_marginal(tr_df, a, "wtperfin")
        d_syn = tvd(te, sy); d_tr = tvd(te, trm)
        ratio = d_syn / d_tr if d_tr > 1e-6 else float("nan")
        ratios.append(ratio)
        md.append(f"| {a} | {d_syn:.3f} | {d_tr:.3f} | {ratio:.2f} |")
    fig, ax = newfig(6.2, 3.8)
    valid = [(a, r) for a, r in zip(ATTRS, ratios) if np.isfinite(r)]
    ax.barh([LBL.get(a, a) for a, _ in valid], [r for _, r in valid], color=SYNTH)
    ax.axvline(1.0, color=ACCENT, ls="--", lw=1, label="ideal (synth ≈ sampling noise)")
    ax.set_xlabel("TVD(synth,TEST) / TVD(TRAIN,TEST)")
    ax.set_title("Generalisation: synthetic vs held-out TEST"); ax.legend()
    save(fig, G_DIR, "fig_G_generalisation_ratio")
    md.append(f"\nmedian ratio = {np.nanmedian(ratios):.2f} (≈1 ⇒ synth as close to TEST as TRAIN is)\n")

    # ============================ H. MEMORISATION / DCR ============================
    # Nearest-neighbour distance to closest TRAIN record: synth vs holdout (SDMetrics
    # DCROverfittingProtection). Mixed features -> one-hot categoricals + z-age.
    dcr_cat = ["home_county", "home_type", "home_ownership", "hh_income_detailed", "hhsize",
               "numworkers", "numvehicle", "gender", "license", "employment_status"]
    codec = DataCodec(dcr_cat, ["age"]).fit(tr_df)

    def feat(df):
        e = codec.encode(df, device=DEV)
        parts = [F.one_hot(e[c], codec.cardinalities()[c]).float() for c in dcr_cat]
        parts.append(e["age"].unsqueeze(-1))          # z-scored age
        return torch.cat(parts, dim=-1)

    # EQUAL-SIZED references (SDMetrics protocol): a larger reference set is trivially
    # closer, so subsample TRAIN to the HOLDOUT size before comparing DCRs.
    nref = len(hold)
    Ftr = feat(tr_df.sample(nref, random_state=3)); Fho = feat(hold)
    syn_dcr = syn.sample(4000, random_state=7).copy()
    syn_dcr["age"] = pd.to_numeric(syn_dcr.age, errors="coerce").fillna(tr_df.age.median())
    Fsy = feat(syn_dcr)

    def min_dist(Q, R, bs=1000):
        out = []
        for i in range(0, Q.shape[0], bs):
            dm = torch.cdist(Q[i:i + bs], R)          # euclidean
            out.append(dm.min(1).values)
        return torch.cat(out).cpu().numpy()

    dcr_syn_tr = min_dist(Fsy, Ftr); dcr_syn_ho = min_dist(Fsy, Fho)
    dcr_ho_tr = min_dist(Fho, feat(tr_df.sample(nref, random_state=11)))
    share_closer = float((dcr_syn_tr < dcr_syn_ho).mean())    # ~0.5 ⇒ no overfitting
    fig, ax = newfig(5.4, 3.6)
    bins = np.linspace(0, max(dcr_syn_tr.max(), dcr_ho_tr.max()), 40)
    ax.hist(dcr_ho_tr, bins=bins, density=True, alpha=0.55, color=SURVEY, label="holdout → train (baseline)")
    ax.hist(dcr_syn_tr, bins=bins, density=True, alpha=0.55, color=SYNTH, label="synthetic → train")
    ax.set_xlabel("distance to closest training record (DCR)"); ax.set_ylabel("density")
    ax.set_title("Memorisation check — DCR")
    ax.legend()
    save(fig, H_DIR, "fig_H_memorisation_dcr")
    md += ["## H. Memorisation / privacy (DCR)\n",
           f"median DCR synth→train {np.median(dcr_syn_tr):.3f} vs holdout→train "
           f"{np.median(dcr_ho_tr):.3f} (synth ≥ holdout ⇒ no copying)",
           f"share of synth closer to train than to holdout = {share_closer:.3f} "
           f"(≈0.5 ideal; >0.5 flags overfitting)",
           f"exact-duplicate synth→train (DCR=0): {float((dcr_syn_tr==0).mean())*100:.2f}%\n"]

    (OUT / "validation_summary.md").write_text("\n".join(md) + "\n")
    n_fig = len(list(OUT.rglob("*.pdf")))
    print(f"[done] {n_fig} separate figures (.pdf+.png) in {sum(1 for _ in OUT.iterdir() if _.is_dir())} "
          f"folders + validation_summary.md -> {OUT}")
    print(f"  marginals mean TVD {np.mean(list(tvds.values())):.3f} | Cramér |Δ| {np.abs(diff[offdiag]).mean():.3f}"
          f" | county r pop {r_pop:.4f} ev {r_ev:.4f} | DCR share {share_closer:.3f}")


if __name__ == "__main__":
    main()
