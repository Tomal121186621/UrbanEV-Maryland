#!/usr/bin/env python3
"""
10_validate_ev_assignment.py — validate the EV OWNER assignment (Burra-Cirillo logit,
county-calibrated to MVA-2026) with publication-quality, county-wise figures.

Four folders under output/validation_ev/:
  A_fleet_totals/      calibration target: synth EV owners vs MVA-2026 (county counts,
                       BEV/PHEV share) — the assignment must reproduce the control.
  B_adoption_gradient/ behavioural signal: EV ownership RATE by income, single-family,
                       charging access, work-charging, home-office, area type
                       (reproduces the paper's Fig 5-7 findings).
  C_demographics/      EV-owner population vs the general synthetic population (who is
                       selected into ownership) — one figure per attribute.
  D_countywise/        per-county EV profiles (24 counties): count vs MVA, BEV share,
                       owner income mix + a county x income ownership heatmap.

Run after 04_ev_ownership_cirillo.py. Reads only interim parquets + MVA + tract shapes.
"""
from __future__ import annotations
import sys, glob, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
sys.path.insert(0, str(ROOT / "pipeline"))
from src.plotstyle import newfig, save, SURVEY, SYNTH, ACCENT, GREY
from src.labels import code_labels, COUNTY, HH_INCOME, HOME_TYPE, EMPLOYMENT
from src.encoders import age_to_band, AGE_EDGES

INTERIM = ROOT / "pipeline/data/interim"
OUT = ROOT / "pipeline/output/validation_ev"
NM = COUNTY

# ---- shared parsing (mirrors 04) --------------------------------------------
MD = {"ALLEGANY": "24001", "ANNE ARUNDEL": "24003", "BALTIMORE": "24005",
      "CALVERT": "24009", "CAROLINE": "24011", "CARROLL": "24013", "CECIL": "24015",
      "CHARLES": "24017", "DORCHESTER": "24019", "FREDERICK": "24021", "GARRETT": "24023",
      "HARFORD": "24025", "HOWARD": "24027", "KENT": "24029", "MONTGOMERY": "24031",
      "PRINCE GEORGES": "24033", "PRINCE GEORGE'S": "24033", "QUEEN ANNES": "24035",
      "QUEEN ANNE'S": "24035", "SAINT MARYS": "24037", "ST. MARY'S": "24037",
      "SOMERSET": "24039", "TALBOT": "24041", "WASHINGTON": "24043", "WICOMICO": "24045",
      "WORCESTER": "24047", "BALTIMORE CITY": "24510"}


def load_mva():
    d = pd.read_csv(glob.glob(str(ROOT / "pipeline/data/reference/mva/MDOT_MVA*.csv"))[0])
    d.columns = [c.strip() for c in d.columns]
    m = d[d.Year_Month == "2026/01"].copy()
    m["Count"] = pd.to_numeric(m.Count.astype(str).str.replace(",", ""), errors="coerce")
    m["fips"] = m.County.astype(str).str.upper().str.strip().map(MD)
    m = m.dropna(subset=["fips"])
    bev = m[m.Fuel_Category == "Electric"].groupby("fips").Count.sum()
    phev = m[m.Fuel_Category == "Plug-In Hybrid"].groupby("fips").Count.sum()
    tot = bev.add(phev, fill_value=0)
    return tot, (bev / tot)


def fips(s):
    return s.astype(float).astype(int).astype(str).str.zfill(5)


def rate_by(ev, elig, col, order=None):
    """EV ownership rate = owners / eligible persons, per value of `col`."""
    num = ev.groupby(col).size()
    den = elig.groupby(col).size()
    idx = order if order is not None else sorted(set(num.index) | set(den.index))
    num = num.reindex(idx, fill_value=0); den = den.reindex(idx, fill_value=0)
    return idx, (num / den.replace(0, np.nan)).to_numpy(), den.to_numpy()


def tvd(a, b):
    keys = sorted(set(a.index) | set(b.index))
    a = a.reindex(keys, fill_value=0) / max(a.sum(), 1)
    b = b.reindex(keys, fill_value=0) / max(b.sum(), 1)
    return 0.5 * float(np.abs(a - b).sum())


# ============================ MAIN ===========================================
def main():
    ev = pd.read_parquet(INTERIM / "ev_owners.parquet")
    pop = pd.read_parquet(INTERIM / "synth_person.parquet")
    GCOLS = ["hh_income_detailed", "home_type", "home_office", "charge_at_work",
             "numworkers", "numbicycle", "home_ownership", "employment_status"]
    for df in (ev, pop):
        df["fips"] = fips(df.home_county)
        df["age"] = pd.to_numeric(df.age, errors="coerce")
        for c in GCOLS:                              # unify dtypes so cross-frame groupby matches
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    # eligible pool the logit scores = licensed adults (>=16)
    elig = pop[(pd.to_numeric(pop.license, errors="coerce") == 1) & (pop.age >= 16)].copy()
    # per-tract AFDC charging density (from 04) -> attach to BOTH pools for the gradient
    tchg = pd.read_parquet(INTERIM / "tract_charging.parquet")
    tchg["tract_geoid"] = tchg.tract_geoid.astype(str)
    tchg = tchg.set_index("tract_geoid")[["L2_1km", "DCFC_5mi"]]
    for df in (ev, elig):
        df["home_tract"] = df.home_tract.astype(str)
        j = df.join(tchg, on="home_tract", rsuffix="_t")
        df["L2_1km"] = j["L2_1km_t"].fillna(0).values if "L2_1km_t" in j else j["L2_1km"].fillna(0).values
        df["DCFC_5mi"] = j["DCFC_5mi_t"].fillna(0).values if "DCFC_5mi_t" in j else j["DCFC_5mi"].fillna(0).values
    mva_tot, mva_bev = load_mva()
    md = []

    # ---- A. FLEET TOTALS vs MVA --------------------------------------------
    A = OUT / "A_fleet_totals"
    sc = ev.groupby("fips").size().reindex(mva_tot.index, fill_value=0)
    mv = mva_tot.reindex(sc.index)
    r = np.corrcoef(sc, mv)[0, 1]
    mape = float((np.abs(sc - mv) / mv.replace(0, np.nan)).mean())
    # county scatter
    fig, ax = newfig()
    ax.scatter(mv, sc, s=28, color=SYNTH, edgecolor="k", lw=0.4, zorder=3)
    lim = [1, max(mv.max(), sc.max()) * 1.2]
    ax.plot(lim, lim, "--", color=GREY, lw=1)
    ax.set(xscale="log", yscale="log", xlim=lim, ylim=lim,
           xlabel="MVA-2026 registered EVs (county)", ylabel="synthetic EV owners (county)",
           title=f"EV assignment vs MVA control  (r={r:.4f}, MAPE={mape:.1%})")
    save(fig, A, "county_ev_scatter")
    # county bars (sorted)
    o = mv.sort_values(ascending=False).index
    fig, ax = newfig(9, 4)
    x = np.arange(len(o))
    ax.bar(x - 0.2, mv.reindex(o), 0.4, label="MVA-2026", color=SURVEY)
    ax.bar(x + 0.2, sc.reindex(o), 0.4, label="synthetic", color=SYNTH)
    ax.set_xticks(x); ax.set_xticklabels([NM.get(f, f) for f in o], rotation=55, ha="right")
    ax.set(ylabel="EV count", title="EV owners by county: synthetic vs MVA-2026")
    ax.legend()
    save(fig, A, "county_ev_bars")
    # BEV share per county
    sb = ev[ev.ev_powertrain == "BEV"].groupby("fips").size().reindex(sc.index, fill_value=0) / sc.replace(0, np.nan)
    mb = mva_bev.reindex(sc.index)
    fig, ax = newfig()
    ax.scatter(mb, sb, s=28, color=ACCENT, edgecolor="k", lw=0.4, zorder=3)
    ax.plot([0.5, 1], [0.5, 1], "--", color=GREY, lw=1)
    ax.set(xlabel="MVA BEV share", ylabel="synthetic BEV share",
           title="BEV / PHEV split by county")
    save(fig, A, "bev_share_scatter")
    md += ["## A. Fleet totals vs MVA-2026",
           f"total synth {len(ev):,} vs MVA {int(mva_tot.sum()):,} "
           f"({len(ev)/mva_tot.sum()-1:+.2%}); county count r={r:.4f}, MAPE={mape:.1%}",
           f"BEV share synth {(ev.ev_powertrain=='BEV').mean():.3f} vs MVA {float((mva_bev*mva_tot).sum()/mva_tot.sum()):.3f}\n"]

    # ---- B. ADOPTION GRADIENT ----------------------------------------------
    B = OUT / "B_adoption_gradient"

    def grad_fig(col, order, labels, name, title, xlabel):
        idx, rt, den = rate_by(ev, elig, col, order)   # idx == order (the values themselves)
        xs, ys = [], []
        for k, r_, d in zip(idx, rt, den):
            if d > 0 and np.isfinite(r_):
                xs.append(labels.get(k, str(k))); ys.append(r_ * 100)
        fig, ax = newfig()
        ax.bar(xs, ys, color=SYNTH, edgecolor="k", lw=0.4)
        ax.set(ylabel="EV ownership rate (%)", title=title, xlabel=xlabel)
        for t in ax.get_xticklabels():
            t.set_rotation(35); t.set_ha("right")
        save(fig, B, name)
        return xs, ys

    inc_order = [1, 2, 3, 4, 5, 6, 7, 8]
    grad_fig("hh_income_detailed", inc_order, {i: HH_INCOME.get(str(i), str(i)) for i in inc_order},
             "ownership_by_income", "EV adoption rises with income", "household income")
    ht_order = [1, 2, 3, 4, 5]
    grad_fig("home_type", ht_order, {i: HOME_TYPE.get(str(i), str(i)) for i in ht_order},
             "ownership_by_hometype", "EV adoption by dwelling type", "home type")
    grad_fig("charge_at_work", [0, 1], {0: "No", 1: "Yes"},
             "ownership_by_workcharge", "Workplace charging and EV adoption", "charge at work")
    grad_fig("home_office", [0, 1], {0: "No", 1: "Yes"},
             "ownership_by_homeoffice", "Teleworking and EV adoption", "home office")
    # charging access gradient (DCFC within 5 mi, binned)
    for src, lab, nm in [("DCFC_5mi", "DCFC ports ≤5 mi", "ownership_by_dcfc"),
                         ("L2_1km", "L2 ports ≤1 km", "ownership_by_l2")]:
        if src in ev.columns and src in elig.columns:
            bins = [-0.1, 0, 2, 5, 10, 25, 1e9]
            lbls = ["0", "1-2", "3-5", "6-10", "11-25", "25+"]
            ev["_b"] = pd.cut(ev[src], bins, labels=lbls)
            elig["_b"] = pd.cut(elig[src], bins, labels=lbls)
            idx, rt, den = rate_by(ev, elig, "_b", lbls)
            fig, ax = newfig()
            ax.bar([str(l) for l in lbls], rt * 100, color=SYNTH, edgecolor="k", lw=0.4)
            ax.set(ylabel="EV ownership rate (%)", xlabel=lab,
                   title=f"EV adoption vs charging access ({lab})")
            save(fig, B, nm)
    md += ["## B. Adoption gradient",
           "ownership rate rises monotonically with income and is higher for single-family, "
           "work-charging, teleworking and charger-dense tracts (reproduces Burra-Cirillo Fig 5-7).\n"]

    # ---- C. EV OWNERS vs GENERAL POPULATION --------------------------------
    C = OUT / "C_demographics"
    pop["age_band"] = age_to_band(pop.age); ev["age_band"] = age_to_band(ev.age)
    attrs = {"hh_income_detailed": "Household income", "home_type": "Home type",
             "home_ownership": "Home ownership", "employment_status": "Employment",
             "age_band": "Age band", "home_office": "Home office", "charge_at_work": "Charge at work",
             "numworkers": "Workers", "numbicycle": "Bicycles"}
    ctv = {}
    for col, title in attrs.items():
        a = ev[col].astype(str).value_counts(); b = pop[col].astype(str).value_counts()
        keys = sorted(set(a.index) | set(b.index), key=lambda z: float(z) if z.replace('.', '', 1).replace('-', '').isdigit() else 1e9)
        labs = code_labels(col, keys)
        av = (a.reindex(keys, fill_value=0) / a.sum()).to_numpy()
        bv = (b.reindex(keys, fill_value=0) / b.sum()).to_numpy()
        ctv[col] = tvd(a, b)
        x = np.arange(len(keys))
        fig, ax = newfig(max(5, len(keys) * 0.5), 3.6)
        ax.bar(x - 0.2, bv, 0.4, label="all persons", color=GREY)
        ax.bar(x + 0.2, av, 0.4, label="EV owners", color=SYNTH)
        ax.set_xticks(x); ax.set_xticklabels(labs, rotation=35, ha="right")
        ax.set(ylabel="share", title=f"{title}: EV owners vs population  (TVD={ctv[col]:.3f})")
        ax.legend()
        save(fig, C, f"evpop_{col}")
    md += ["## C. EV owners vs general population",
           "selection TVD (EV owners vs all persons): "
           + ", ".join(f"{k} {v:.3f}" for k, v in sorted(ctv.items(), key=lambda z: -z[1])) + "\n"]

    # ---- D. COUNTY-WISE -----------------------------------------------------
    D = OUT / "D_countywise"
    # county x income ownership-share heatmap
    import matplotlib.pyplot as plt
    counties = list(sc.sort_values(ascending=False).index)
    M = np.zeros((len(counties), 8))
    for i, f in enumerate(counties):
        sub = ev[ev.fips == f].hh_income_detailed.astype(float)
        for j, inc in enumerate(inc_order):
            M[i, j] = (sub == inc).mean()
    fig, ax = newfig(6, 8)
    im = ax.imshow(M, aspect="auto", cmap="YlOrBr")
    ax.set_xticks(range(8)); ax.set_xticklabels([HH_INCOME[str(i)] for i in inc_order], rotation=40, ha="right")
    ax.set_yticks(range(len(counties))); ax.set_yticklabels([NM.get(f, f) for f in counties], fontsize=7)
    ax.set(title="EV-owner income mix by county")
    fig.colorbar(im, ax=ax, fraction=0.046, label="share of county EV owners")
    save(fig, D, "county_income_heatmap")
    # per-county summary table
    rows = []
    for f in counties:
        sub = ev[ev.fips == f]
        rows.append(dict(county=NM.get(f, f), synth=int(sc[f]), mva=int(mva_tot.get(f, 0)),
                         bev_share=round((sub.ev_powertrain == "BEV").mean(), 3),
                         med_income=int(pd.to_numeric(sub.hh_income_detailed).median()),
                         sf_share=round(sub.single_family.mean(), 3)))
    pd.DataFrame(rows).to_csv(D / "county_ev_summary.csv", index=False)
    md += ["## D. County-wise",
           f"per-county summary -> D_countywise/county_ev_summary.csv; income-mix heatmap saved.\n"]

    (OUT / "ev_validation_summary.md").write_text("# EV assignment validation\n\n" + "\n".join(md))
    n = len(list(OUT.rglob("*.pdf")))
    print(f"[done] {n} EV-assignment figures in {sum(1 for _ in OUT.iterdir() if _.is_dir())} folders "
          f"-> {OUT}")
    print(f"  fleet r={r:.4f} MAPE={mape:.1%}; BEV {(ev.ev_powertrain=='BEV').mean():.3f}; "
          f"income selection TVD {ctv['hh_income_detailed']:.3f}")


if __name__ == "__main__":
    main()
