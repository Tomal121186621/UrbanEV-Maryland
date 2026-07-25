#!/usr/bin/env python3
"""
tax_incidence_paired.py — paired-plan tax-incidence accounting for Phase 7 policy sweep.

Reads baseline + policy charging_sessions.csv from the final (frozen) iteration of each
run and computes the tax-incidence side of the welfare comparison **without** relying on
MATSim's exec-score (which is contaminated by warm-start optimization depth — see deep
diagnosis dated 2026-06-29).

Methodology
-----------
For each charger type t in {home, work, L2, DCFC, DCFC_TESLA}:
  Δprice_t = policy_unit_price_t - baseline_unit_price_t  ($/kWh)

Tax revenue        = Σ_sessions[policy]  Δprice_{charger_type} × energy_kwh
Per-agent tax      = group_by(person_id).sum(Δprice × energy_kwh)
Per-bucket equity  = group_by(income_bucket).{mean,p50,p90,sum} of per-agent tax

For the disutility side (in MATSim utility units, comparable across runs without warm-start
contamination):
  Δ_disutility_per_agent = β_money × per_agent_tax     (β_money < 0)

The per-agent disutility is more rigorous than exec-score Δ because it isolates the price
shock from confounding optimization-depth differences (S1 had 16 innovation iters on top
of baseline's 50 = effectively 66 iters of search, vs baseline's 50, so S1's exec score is
artificially higher).

Inputs
------
  --baseline-dir   Path to baseline output dir (must contain ITERS/it.N/N.charging_sessions.csv
                   for the final iter N).
  --policy-dir     Path to policy output dir (same structure).
  --baseline-cfg   baseline.xml (to read baseline unit prices).
  --policy-cfg     policy_SX.xml (to read policy unit prices).
  --iter-baseline  Iteration to use from baseline (default: max).
  --iter-policy    Iteration to use from policy (default: max).
  --output-csv     Path to write per-agent CSV (default: <policy-dir>/tax_incidence_per_agent.csv).
  --summary-md     Path to write markdown summary (default: <policy-dir>/tax_incidence_summary.md).

Usage
-----
  py analysis/tax_incidence_paired.py \
      --baseline-dir output/final_runs/baseline \
      --policy-dir   output/final_runs/policy_S1 \
      --baseline-cfg scenarios/maryland/final/baseline.xml \
      --policy-cfg   scenarios/maryland/final/policy_S1.xml

The script also prints a console summary suitable for paste into reports.
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

import pandas as pd

CHARGER_TYPES = ["home", "work", "L2", "DCFC", "DCFC_TESLA"]

PRICE_PARAM_BY_TYPE = {
    "home": "homeChargingCost",
    "work": "workChargingCost",
    "L2": "publicL2Cost",
    "DCFC": "publicDcfcCost",
    "DCFC_TESLA": "publicDcfcTeslaCost",
}


def parse_prices_from_config(cfg_path: Path) -> dict[str, float]:
    """Extract per-type unit price from a MATSim XML config (urban_ev module params)."""
    text = cfg_path.read_text(encoding="utf-8")
    out: dict[str, float] = {}
    for t, pname in PRICE_PARAM_BY_TYPE.items():
        m = re.search(rf'<param\s+name="{pname}"\s+value="([0-9eE.+-]+)"', text)
        if not m:
            raise ValueError(f"price param {pname!r} not found in {cfg_path}")
        out[t] = float(m.group(1))
    return out


def find_final_iter(run_dir: Path, override: int | None = None) -> int:
    iters_dir = run_dir / "ITERS"
    if not iters_dir.exists():
        raise FileNotFoundError(f"ITERS/ missing under {run_dir}")
    ns = sorted(
        int(p.name.split(".", 1)[1]) for p in iters_dir.iterdir()
        if p.is_dir() and p.name.startswith("it.")
    )
    if not ns:
        raise FileNotFoundError(f"no it.N directories under {iters_dir}")
    return override if override is not None else ns[-1]


def load_sessions(run_dir: Path, it: int) -> pd.DataFrame:
    csv_path = run_dir / "ITERS" / f"it.{it}" / f"{it}.charging_sessions.csv"
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    df = pd.read_csv(csv_path, sep=";")
    # normalize charger_type column to our canonical labels
    # In the upstream CSV, charger_type is one of: L1, L2, DCFC, DCFC_TESLA, home (no work column).
    # work-typed sessions appear as activity_type starting with "work" AND charger_type == "L2"
    # (or DCFC at fleet sites). To avoid ambiguity, we keep the raw charger_type and add a
    # derived 'effective_type' that splits work-L2 out of public-L2 based on activity_type.
    df["effective_type"] = df["charger_type"]
    work_mask = (df["activity_type"].str.startswith("work", na=False)) & (df["charger_type"] == "L2")
    df.loc[work_mask, "effective_type"] = "work"
    # home stays "home" if charger_type is already labelled "home" in upstream;
    # otherwise infer from activity_type
    home_mask = (df["activity_type"].str.startswith("home", na=False))
    df.loc[home_mask, "effective_type"] = "home"
    return df


def compute_incidence(df: pd.DataFrame, delta_price: dict[str, float]) -> pd.DataFrame:
    """Add a 'tax_usd' column = Δprice × energy_kwh for each session."""
    df = df.copy()
    df["delta_price"] = df["effective_type"].map(delta_price).fillna(0.0)
    df["tax_usd"] = df["delta_price"] * df["energy_kwh"]
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline-dir", required=True, type=Path)
    ap.add_argument("--policy-dir", required=True, type=Path)
    ap.add_argument("--baseline-cfg", required=True, type=Path)
    ap.add_argument("--policy-cfg", required=True, type=Path)
    ap.add_argument("--iter-baseline", type=int, default=None)
    ap.add_argument("--iter-policy", type=int, default=None)
    ap.add_argument("--output-csv", type=Path, default=None)
    ap.add_argument("--summary-md", type=Path, default=None)
    args = ap.parse_args()

    out_csv = args.output_csv or (args.policy_dir / "tax_incidence_per_agent.csv")
    out_md = args.summary_md or (args.policy_dir / "tax_incidence_summary.md")

    # 1. prices
    p_base = parse_prices_from_config(args.baseline_cfg)
    p_pol = parse_prices_from_config(args.policy_cfg)
    delta = {t: p_pol[t] - p_base[t] for t in CHARGER_TYPES}

    # 2. sessions (policy run drives the accounting — its kWh × Δprice = revenue)
    it_pol = find_final_iter(args.policy_dir, args.iter_policy)
    it_base = find_final_iter(args.baseline_dir, args.iter_baseline)
    df_pol = load_sessions(args.policy_dir, it_pol)
    df_base = load_sessions(args.baseline_dir, it_base)

    # 3. incidence per session, per agent
    df_pol = compute_incidence(df_pol, delta)
    per_agent = (df_pol.groupby("person_id")
                       .agg(tax_usd=("tax_usd", "sum"),
                            kwh_total=("energy_kwh", "sum"),
                            n_sessions=("session_id", "count"),
                            income_bucket=("income_bucket", "first"),
                            income_usd=("income_usd", "first"),
                            ev_type=("ev_type", "first"),
                            home_kw=("home_charger_power_kw", "first"),
                            beta_money=("beta_money", "first"))
                       .reset_index())
    per_agent["disutility"] = per_agent["beta_money"] * per_agent["tax_usd"]
    per_agent.to_csv(out_csv, index=False)

    # 4. aggregate summaries
    by_type_pol = (df_pol.groupby("effective_type")
                          .agg(kwh=("energy_kwh", "sum"),
                               tax_usd=("tax_usd", "sum"),
                               n_sessions=("session_id", "count")))
    by_type_base = (df_base.groupby("effective_type")
                           .agg(kwh=("energy_kwh", "sum"),
                                n_sessions=("session_id", "count")))

    by_bucket = (per_agent.groupby("income_bucket")
                          .agg(n_agents=("person_id", "count"),
                               tax_total=("tax_usd", "sum"),
                               tax_mean=("tax_usd", "mean"),
                               tax_p50=("tax_usd", "median"),
                               tax_p90=("tax_usd", lambda s: s.quantile(0.90)),
                               disutility_mean=("disutility", "mean"))
                          .sort_index())

    # 5. console + markdown summary
    lines = []
    lines.append(f"# Tax Incidence Paired Analysis\n")
    lines.append(f"Baseline run: `{args.baseline_dir}` (iter {it_base})  ")
    lines.append(f"Policy run:   `{args.policy_dir}` (iter {it_pol})\n")
    lines.append(f"## Unit prices ($/kWh)\n")
    lines.append("| type | baseline | policy | Δ |\n|---|---|---|---|")
    for t in CHARGER_TYPES:
        lines.append(f"| {t} | {p_base[t]:.3f} | {p_pol[t]:.3f} | {delta[t]:+.3f} |")
    lines.append("\n## Charger-type aggregates (final iter)\n")
    lines.append("| type | baseline_kWh | policy_kWh | Δ_kWh | Δ_kWh% | policy_n_sess | policy_tax_USD |\n|---|---|---|---|---|---|---|")
    for t in CHARGER_TYPES:
        bk = by_type_base["kwh"].get(t, 0.0)
        pk = by_type_pol["kwh"].get(t, 0.0)
        ns = int(by_type_pol["n_sessions"].get(t, 0))
        tx = by_type_pol["tax_usd"].get(t, 0.0)
        dpct = (pk - bk) / bk * 100 if bk > 0 else float("nan")
        lines.append(f"| {t} | {bk:,.0f} | {pk:,.0f} | {pk-bk:+,.0f} | {dpct:+.1f}% | {ns:,} | {tx:,.2f} |")
    total_tax = float(per_agent["tax_usd"].sum())
    lines.append(f"\n**Total tax revenue (policy run, one sim-day): ${total_tax:,.2f}**\n")
    lines.append(f"\n**Total kWh charged (policy run): {df_pol['energy_kwh'].sum():,.0f} kWh**\n")

    lines.append("\n## Equity by income bucket\n")
    lines.append("| bucket | n_agents | tax_total_USD | tax_mean_USD | tax_p50 | tax_p90 | Δ_disutility_mean |\n|---|---|---|---|---|---|---|")
    for bk, row in by_bucket.iterrows():
        lines.append(
            f"| {bk} | {int(row['n_agents']):,} | {row['tax_total']:,.2f} | "
            f"{row['tax_mean']:.4f} | {row['tax_p50']:.4f} | {row['tax_p90']:.4f} | "
            f"{row['disutility_mean']:+.5f} |"
        )

    lines.append("\n## Annualized projections\n")
    sim_day_factor_weekday = 260  # weekdays/yr
    sim_day_factor_calendar = 365
    lines.append(f"- ×{sim_day_factor_weekday} weekdays: ${total_tax * sim_day_factor_weekday:,.0f}/yr")
    lines.append(f"- ×{sim_day_factor_calendar} calendar days: ${total_tax * sim_day_factor_calendar:,.0f}/yr")

    summary_text = "\n".join(lines) + "\n"
    out_md.write_text(summary_text, encoding="utf-8")
    print(summary_text)
    print(f"\n[wrote per-agent CSV]: {out_csv}")
    print(f"[wrote markdown summary]: {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
