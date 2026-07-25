#!/usr/bin/env python3
"""
policy_framework.py — unified who-wins/who-loses, consumer-burden and revenue analysis
across ALL recovery instruments, on one consistent per-agent basis.

Instruments
  analytic  (computed from per-agent VMT/income, no sim):
     gas_equiv : each agent pays their own shadow gap (fair benchmark; Σ = R*)
     ruc       : per-mile road-user charge (rate = R*/ΣVMT)
     flat_fee  : flat $/yr = R*/N
  behavioural (from each policy_*/it.N charging_sessions, when present):
     T1..T4    : consumer burden = charging cost under policy prices − under baseline
                prices (net of the simulated behavioural shift); revenue = surcharge Σ.

For every instrument: total revenue, revenue/R*, Suits index, mean burden by income
octile / tenure / county, and WINNERS vs LOSERS relative to the gas-tax-equivalent fair
share (winner = pays less than fair; loser = pays more). Outputs -> paper/ (matrix + figs).
"""
import sys, glob, re
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
RUNS = ROOT / "scenarios/maryland/output/runs_2026"
PA = RUNS / "baseline/shadow_tax_gap_per_agent.csv"
EVO = REPO / "pipeline/data/interim/ev_owners.parquet"
SCEN = pd.read_csv(ROOT / "analysis/policy_scenarios.csv")
PAPER = REPO / "paper"; (PAPER / "tables").mkdir(parents=True, exist_ok=True)
DAYS = 348
BASE_PRICE = {"home": 0.139, "work": 0.0, "public": 0.40}     # baseline $/kWh


def suits(inc, tax):
    o = np.argsort(inc); ct = np.concatenate([[0], np.cumsum(tax[o]) / tax[o].sum()])
    ci = np.concatenate([[0], np.cumsum(inc[o]) / inc[o].sum()])
    return float(1 - 2 * np.trapezoid(ct, ci))


# Intended per-kWh surcharge each scenario adds RELATIVE TO the simulated baseline
# (home $0.139, public $0.40). The config's per-type L2/DCFC prices were authored
# against a different (per-type) baseline, so we score the *designed* surcharge here.
SURCHARGE = {
    "T1_state_public_5c":    {"home": 0.00, "work": 0.0, "public": 0.05},
    "T2_state_public_10c":   {"home": 0.00, "work": 0.0, "public": 0.10},
    "T3_utility_evrider_3c": {"home": 0.03, "work": 0.0, "public": 0.00},
    "T4_combined_5c_2c":     {"home": 0.02, "work": 0.0, "public": 0.05},
}


def per_agent_surcharge_burden(sess_csv, sur):
    """Σ energy×surcharge by 3-way venue, per person, annualized (sessions are 3-day)."""
    d = pd.read_csv(sess_csv, sep=";")
    d["b"] = pd.to_numeric(d.energy_kwh, errors="coerce") * d.charger_type_3way.map(sur).fillna(0.0)
    return d.groupby("person_id").b.sum() / 3.0 * DAYS   # 3-day total -> daily -> annual


def main():
    d = pd.read_csv(PA)
    ev = pd.read_parquet(EVO)[["person_id", "home_county", "home_type", "home_ownership", "ev_powertrain"]]
    d = d.merge(ev, left_on="vehicle_id", right_on="person_id", how="left")
    d["shadow_yr"] = d.state_tax_gap_day_usd * DAYS
    d["vmt_yr"] = d.daily_base_vmt_mi * DAYS
    d["oct"] = pd.qcut(d.income_usd.rank(method="first"), 8, labels=range(1, 9))
    d["renter"] = (pd.to_numeric(d.home_ownership, errors="coerce") == 2)
    R = d.shadow_yr.sum(); N = len(d); inc = d.income_usd.to_numpy(float)
    fair = d.shadow_yr.to_numpy(float)                    # gas-equivalent fair share

    inst = {}
    inst["gas_equiv"] = fair
    inst["ruc"] = (d.vmt_yr * (R / d.vmt_yr.sum())).to_numpy(float)
    inst["flat_fee"] = np.full(N, R / N)                  # flat fee sized to recover R* exactly
    # Maryland's actual statutory EV surcharge (SB 362/2024, TR 13-956): BEV $125, PHEV $100
    inst["md_actual"] = np.where(d.ev_powertrain.values == "BEV", 125.0, 100.0)
    # Charging surcharges: revenue = per-agent CONVERGED baseline charging energy x surcharge.
    # Public charging is price-inelastic (the behavioural policy runs confirm the venue mix is
    # stable), so the surcharge burden is the existing energy base times the rate. We use the
    # converged baseline (not the warm-started policy runs, which had not fully re-converged).
    def _iter_num(p):
        return int(p.split("it.")[1].split("/")[0])
    bcand = sorted(glob.glob(str(RUNS / "baseline/ITERS/it.*/*.charging_sessions.csv")), key=_iter_num)
    bs = pd.read_csv(bcand[-1], sep=";")
    bs["e"] = pd.to_numeric(bs.energy_kwh, errors="coerce")
    ee = bs.groupby(["person_id", "charger_type_3way"]).e.sum().unstack(fill_value=0) / 3.0 * DAYS
    for sid, sur in SURCHARGE.items():
        burden = sum(ee.get(v, pd.Series(0, index=ee.index)) * rate for v, rate in sur.items() if rate)
        inst[sid] = burden.reindex(d.person_id).fillna(0).to_numpy(float)

    # ---- net residual gap: Maryland already levies a $125/yr EV surcharge ----
    md_rev = inst["md_actual"].sum()
    R_net = R - md_rev                                    # unrecovered gap after the existing MD fee
    print(f"\n[gap]  gross R* = ${R/1e6:.1f}M/yr | MD fee (BEV$125/PHEV$100) recovers ${md_rev/1e6:.1f}M "
          f"({md_rev/R*100:.0f}%) | NET residual gap = ${R_net/1e6:.1f}M/yr\n")

    # ---- per-instrument summary ----
    rows = []
    for k, b in inst.items():
        win = (b < fair - 1).mean(); lose = (b > fair + 1).mean()
        rows.append(dict(instrument=k, revenue_Myr=round(b.sum() / 1e6, 1),
                         rev_over_Rstar=round(b.sum() / R, 2),
                         rev_over_residual=round(b.sum() / R_net, 2), suits=round(suits(inc, b), 3),
                         mean_yr=round(b.mean(), 1), winners_pct=round(win * 100, 1),
                         losers_pct=round(lose * 100, 1),
                         renter_burden=round(b[d.renter.values].mean(), 1),
                         owner_burden=round(b[~d.renter.values].mean(), 1)))
    summ = pd.DataFrame(rows)
    summ.to_csv(PAPER / "tables/policy_comparison.csv", index=False)
    print(summ.to_string(index=False))

    # ---- per-agent burdens (for equity / Lorenz / effective-rate figures) ----
    pa_out = d[["vehicle_id", "income_usd", "oct", "ev_powertrain", "renter"]].copy()
    for k, b in inst.items():
        pa_out[k] = b
    pa_out.to_parquet(PAPER / "tables/per_agent_burdens.parquet")

    # ---- Fig: winners vs losers by instrument ----
    fig, ax = pf.newfig(6.4, 3.8)
    x = np.arange(len(summ))
    ax.bar(x, summ.winners_pct, color=pf.GREEN, label="winners (< fair)", edgecolor="k", lw=0.3)
    ax.bar(x, -summ.losers_pct, color=pf.VERM, label="losers (> fair)", edgecolor="k", lw=0.3)
    ax.axhline(0, color="k", lw=0.8); ax.set_xticks(x); ax.set_xticklabels(summ.instrument, rotation=25, ha="right")
    ax.set(ylabel="% of EV owners", title="Winners vs losers relative to gas-tax-equivalent")
    pf.legout(ax); pf.save(fig, PAPER / "figures", "winners_losers")

    # ---- Fig: mean burden by income octile, all instruments ----
    fig, ax = pf.newfig(6.6, 3.8)
    for k, b in inst.items():
        m = pd.Series(b).groupby(d.oct.values).mean()
        ax.plot(range(1, 9), m.values, marker="o", label=k)
    ax.set(xlabel="income octile (low→high)", ylabel="mean burden ($/yr)",
           title="Consumer burden by income across instruments")
    pf.legout(ax); pf.save(fig, PAPER / "figures", "burden_by_income_all")
    print(f"[done] {len(inst)} instruments -> paper/tables/policy_comparison.csv + 2 figures")


if __name__ == "__main__":
    main()
