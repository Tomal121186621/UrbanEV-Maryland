#!/usr/bin/env python3
"""
incidence_analysis.py — equity/incidence of the shadow gas-tax gap and the analytic
recovery instruments (no simulation needed; charging-based T1-T4 come from the sweep).

Instruments, each sized to recover the SAME annual R* (equal-revenue comparison):
  - gas_equiv : each agent pays their own shadow gap (= what their counterfactual ICE
                would have paid) — the fairness benchmark, proportional to electric VMT.
  - ruc       : per-mile road-user charge, rate = R*/total_VMT; burden = VMT * rate.
  - flat_fee  : flat $/yr EV registration surcharge = R*/n_EV (what MD actually adopted).
For each: Suits index (progressivity), Lorenz curve, $/yr burden by income octile, and
burden by housing tenure. Figures -> output/runs_2026/analysis_incidence/.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
PA = ROOT / "scenarios/maryland/output/runs_2026/baseline/shadow_tax_gap_per_agent.csv"
EVO = REPO / "pipeline/data/interim/ev_owners.parquet"
OUT = ROOT / "scenarios/maryland/output/runs_2026/analysis_incidence"
OUT.mkdir(parents=True, exist_ok=True)
DAYS = 348
BLUE, ORANGE, GREEN, GREY = pf.BLUE, pf.ORANGE, pf.GREEN, pf.GREY


def suits(income, tax):
    """Suits index: +progressive / 0 proportional / -regressive."""
    o = np.argsort(income)
    ci = np.cumsum(income[o]); ci = np.concatenate([[0], ci / ci[-1]])
    ct = np.cumsum(tax[o]); ct = np.concatenate([[0], ct / ct[-1]])
    area = np.trapezoid(ct, ci)                       # area under concentration curve
    return float(1 - 2 * area)


def lorenz(income, tax):
    o = np.argsort(income)
    ci = np.concatenate([[0], np.cumsum(income[o]) / income.sum()])
    ct = np.concatenate([[0], np.cumsum(tax[o]) / tax.sum()])
    return ci, ct


def main():
    d = pd.read_csv(PA)
    ev = pd.read_parquet(EVO)[["person_id", "home_county", "home_type", "home_ownership"]]
    d = d.merge(ev, left_on="vehicle_id", right_on="person_id", how="left")
    d["shadow_yr"] = d.state_tax_gap_day_usd * DAYS
    d["vmt_yr"] = d.daily_base_vmt_mi * DAYS
    R = d.shadow_yr.sum()
    n = len(d)
    inc = d.income_usd.to_numpy(float)
    # instruments (equal revenue R)
    d["gas_equiv"] = d.shadow_yr                                   # benchmark
    d["ruc"] = d.vmt_yr * (R / d.vmt_yr.sum())                     # per-mile
    d["flat_fee"] = R / n                                          # flat
    inst = {"gas_equiv": ("Gas-tax equivalent", BLUE),
            "ruc": ("Per-mile RUC", GREEN),
            "flat_fee": ("Flat registration fee", ORANGE)}
    print(f"R* = ${R/1e6:.1f}M/yr | {n:,} EVs | RUC rate ${R/d.vmt_yr.sum()*100:.3f}/100mi | flat ${R/n:.0f}/yr")

    # --- Fig 1: Suits index comparison ---
    sui = {k: suits(inc, d[k].to_numpy(float)) for k in inst}
    fig, ax = plt.subplots(figsize=(5.4, 3.6))
    ks = list(inst)
    ax.bar([inst[k][0] for k in ks], [sui[k] for k in ks], color=[inst[k][1] for k in ks], edgecolor="k", lw=0.4)
    ax.axhline(0, color="k", lw=0.8); ax.set_ylabel("Suits index  (+prog / −regress)")
    ax.set_title("Progressivity of shadow-gap recovery instruments")
    for t in ax.get_xticklabels(): t.set_rotation(15); t.set_ha("right")
    fig.tight_layout(); fig.savefig(OUT / "suits_index.pdf"); fig.savefig(OUT / "suits_index.png"); plt.close(fig)

    # --- Fig 2: Lorenz / concentration curves ---
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color=GREY, lw=1, label="proportional")
    for k in inst:
        ci, ct = lorenz(inc, d[k].to_numpy(float))
        ax.plot(ci, ct, color=inst[k][1], lw=2, label=f"{inst[k][0]} (S={sui[k]:+.3f})")
    ax.set(xlabel="cumulative share of EV households (by income)",
           ylabel="cumulative share of tax burden", title="Tax concentration curves")
    pf.legout(ax)
    fig.tight_layout(); fig.savefig(OUT / "lorenz.pdf"); fig.savefig(OUT / "lorenz.png"); plt.close(fig)

    # --- Fig 3: $/yr burden by income octile ---
    d["oct"] = pd.qcut(d.income_usd.rank(method="first"), 8, labels=range(1, 9))
    g = d.groupby("oct")[list(inst)].mean()
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    x = np.arange(8); w = 0.26
    for i, k in enumerate(inst):
        ax.bar(x + (i - 1) * w, g[k], w, color=inst[k][1], label=inst[k][0], edgecolor="k", lw=0.3)
    ax.set(xticks=x, xlabel="income octile (low → high)", ylabel="mean burden ($/yr)",
           title="Annual burden by income octile")
    ax.set_xticklabels(range(1, 9)); pf.legout(ax)
    fig.tight_layout(); fig.savefig(OUT / "burden_by_income.pdf"); fig.savefig(OUT / "burden_by_income.png"); plt.close(fig)

    # --- Fig 4: burden as % of income by octile (regressivity view) ---
    gp = (d.assign(**{f"{k}_pct": d[k] / d.income_usd * 100 for k in inst})
          .groupby("oct")[[f"{k}_pct" for k in inst]].mean())
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for k in inst:
        ax.plot(range(1, 9), gp[f"{k}_pct"], marker="o", color=inst[k][1], label=inst[k][0])
    ax.set(xlabel="income octile", ylabel="burden as % of income", title="Regressivity profile")
    pf.legout(ax); fig.tight_layout()
    fig.savefig(OUT / "burden_pct_income.pdf"); fig.savefig(OUT / "burden_pct_income.png"); plt.close(fig)

    pd.DataFrame({"instrument": [inst[k][0] for k in inst],
                  "suits_index": [round(sui[k], 4) for k in inst],
                  "mean_$/yr": [round(d[k].mean(), 1) for k in inst]}).to_csv(OUT / "incidence_summary.csv", index=False)
    print("Suits:", {inst[k][0]: round(sui[k], 3) for k in inst})
    print(f"[done] 4 figures + summary -> {OUT}")


if __name__ == "__main__":
    main()
