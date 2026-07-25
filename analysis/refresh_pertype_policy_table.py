#!/usr/bin/env python3
"""Refresh the T1-T4 charging-surcharge policy table with the CONVERGED PER-TYPE runs.
Two revenue estimates per scenario:
  (a) base-energy proxy  : per-type BASELINE energy x designed surcharge (price-inelastic assumption)
  (b) behavioural (sim)  : each policy run's ACTUAL converged energy x surcharge (nets the venue shift)
The gap between (a) and (b) IS the behavioural response. R* is VMT-based (unchanged by prices).
-> paper/tables/policy_comparison_pertype.csv  + prints the T1-T4 block."""
import glob
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
RUNS = ROOT / "scenarios/maryland/output/runs_2026"
PA = RUNS / "baseline/shadow_tax_gap_per_agent.csv"          # VMT/R* (same travel as per-type)
EVO = REPO / "pipeline/data/interim/ev_owners.parquet"
PAPER = REPO / "paper"; DAYS = 348; PLAN = 3.0

SURCHARGE = {   # per-kWh surcharge each scenario adds vs baseline (home/work/public)
    "T1_state_public_5c":    {"public": 0.05},
    "T2_state_public_10c":   {"public": 0.10},
    "T3_utility_evrider_3c": {"home": 0.03},
    "T4_combined_5c_2c":     {"home": 0.02, "public": 0.05},
}
POL_DIR = {s: f"policy_{s}_pertype_100pct" for s in SURCHARGE}


def suits(inc, tax):
    o = np.argsort(inc); ct = np.concatenate([[0], np.cumsum(tax[o]) / tax[o].sum()])
    ci = np.concatenate([[0], np.cumsum(inc[o]) / inc[o].sum()])
    return float(1 - 2 * np.trapezoid(ct, ci))


def latest_sessions(run):
    fs = sorted(glob.glob(str(RUNS / run / "ITERS/it.*/*.charging_sessions.csv")),
                key=lambda p: int(p.split("it.")[1].split("/")[0]))
    return fs[-1] if fs else None


def energy_by_venue(run):
    """per-person annual kWh by 3-way venue from a run's latest iter."""
    f = latest_sessions(run)
    if f is None:
        return None, None
    d = pd.read_csv(f, sep=";"); d["e"] = pd.to_numeric(d.energy_kwh, errors="coerce")
    ee = d.groupby(["person_id", "charger_type_3way"]).e.sum().unstack(fill_value=0) / PLAN * DAYS
    return ee, f.split("ITERS/")[1].split("/")[0]


def burden(ee, sur, index):
    b = sum(ee.get(v, pd.Series(0, index=ee.index)) * r for v, r in sur.items() if r)
    return b.reindex(index).fillna(0).to_numpy(float)


def main():
    d = pd.read_csv(PA)
    ev = pd.read_parquet(EVO)[["person_id", "home_ownership"]]
    d = d.merge(ev, left_on="vehicle_id", right_on="person_id", how="left")
    d["shadow_yr"] = d.state_tax_gap_day_usd * DAYS
    R = d.shadow_yr.sum(); inc = d.income_usd.to_numpy(float)
    fair = d.shadow_yr.to_numpy(float)
    renter = (pd.to_numeric(d.home_ownership, errors="coerce") == 2).values

    base_ee, base_it = energy_by_venue("baseline_pertype")
    print(f"[base] per-type baseline energy from {base_it}  (R*=${R/1e6:.1f}M/yr)\n")

    rows = []
    for sid, sur in SURCHARGE.items():
        b_proxy = burden(base_ee, sur, d.person_id)                 # (a) inelastic proxy
        pol_ee, pol_it = energy_by_venue(POL_DIR[sid])              # (b) actual policy energy
        if pol_ee is not None:
            b_beh = burden(pol_ee, sur, d.person_id)
            resp = (b_beh.sum() - b_proxy.sum()) / b_proxy.sum() * 100 if b_proxy.sum() else 0
            status = pol_it
        else:
            b_beh = b_proxy; resp = float("nan"); status = "n/a"
        rows.append(dict(
            scenario=sid, iter=status,
            rev_proxy_M=round(b_proxy.sum() / 1e6, 2),
            rev_behav_M=round(b_beh.sum() / 1e6, 2),
            behav_resp_pct=round(resp, 1),
            pct_of_Rstar=round(b_beh.sum() / R * 100, 1),
            suits=round(suits(inc, b_beh), 3),
            mean_yr=round(b_beh.mean(), 1),
            winners_pct=round((b_beh < fair - 1).mean() * 100, 1),
            losers_pct=round((b_beh > fair + 1).mean() * 100, 1),
            renter_burden=round(b_beh[renter].mean(), 1),
            owner_burden=round(b_beh[~renter].mean(), 1)))
    summ = pd.DataFrame(rows)
    (PAPER / "tables").mkdir(parents=True, exist_ok=True)
    summ.to_csv(PAPER / "tables/policy_comparison_pertype.csv", index=False)
    print(summ.to_string(index=False))
    print("\nbehav_resp_pct = (behavioural revenue − inelastic-proxy revenue) / proxy  "
          "→ how much the venue shift changes surcharge revenue.")


if __name__ == "__main__":
    main()
