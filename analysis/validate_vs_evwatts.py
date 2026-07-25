#!/usr/bin/env python3
"""
validate_vs_evwatts.py — session-level EVWatts validation for a single MATSim
iter output dir. Wraps the same metric definitions used by
sensitivity_validate.py so calibrated cells and the 100% baseline are scored
on the same yardstick.

Reads:  output/<run>/ITERS/it.<N>/<N>.chargingStats.csv
Writes: output/<run>/validation_evwatts_it<N>.csv  + console summary

Run:
    py analysis/validate_vs_evwatts.py --run output/baseline_calibrated_v2b_100pct --iter 20
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import pandas as pd

# Reuse the well-tested helpers from the calibration-tier validator.
ANALYSIS = Path(__file__).resolve().parent
sys.path.insert(0, str(ANALYSIS))
from sensitivity_validate import (  # noqa: E402
    load_evwatts_md,
    read_charging_stats,
    kl_divergence,
    EVW_EVSE_CSV,
    EVW_SESSION_CSV,
)

REPO = ANALYSIS.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True,
                    help="MATSim run output dir, e.g. output/baseline_calibrated_v2b_100pct")
    ap.add_argument("--iter", type=int, required=True,
                    help="Iteration number to validate")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output CSV path (default: <run>/validation_evwatts_it<N>.csv)")
    args = ap.parse_args()

    run = args.run if args.run.is_absolute() else (REPO / args.run)
    stats_csv = run / "ITERS" / f"it.{args.iter}" / f"{args.iter}.chargingStats.csv"
    if not stats_csv.exists():
        print(f"ERROR: chargingStats.csv not found: {stats_csv}")
        return 2

    print(f"[evwatts] run={run.name}  iter={args.iter}")
    print(f"[evwatts] reading {stats_csv.relative_to(REPO)} ...")
    stats_df = read_charging_stats(stats_csv)
    print(f"          sessions: {len(stats_df):,}")

    print("[evwatts] loading EVWatts MD-metro ground truth ...")
    evw_md = load_evwatts_md(EVW_EVSE_CSV, EVW_SESSION_CSV)
    print(f"          EVWatts MD sessions: {len(evw_md):,}")

    # ---- DCFC share -------------------------------------------------------
    if "chargerType" in stats_df.columns:
        types = stats_df["chargerType"].astype(str)
    else:
        types = stats_df["chargerId"].astype(str).str.lower()
    is_dcfc = types.str.contains("dcfc", na=False)
    sim_dcfc_share = float(is_dcfc.mean()) if len(stats_df) else float("nan")
    evw_dcfc_share = float((evw_md["charge_level"] == "DCFC").mean())

    # ---- Energy KL --------------------------------------------------------
    sim_energies = stats_df.loc[stats_df["transmittedEnergy_kWh"] > 0,
                                "transmittedEnergy_kWh"].astype(float).tolist()
    evw_energies = evw_md["energy_kwh"].astype(float).tolist()
    evw_energy_lo = float(min(evw_energies))
    evw_energy_hi = float(max(evw_energies))
    kl_e = kl_divergence(sim_energies, evw_energies,
                         bins=30, lo=evw_energy_lo, hi=evw_energy_hi)

    # ---- Start-hour KL ----------------------------------------------------
    sim_hours = ((stats_df["startTime"].astype(float) // 3600) % 24
                 ).astype(int).tolist()
    evw_hours = evw_md["start_hour"].astype(int).tolist()
    kl_h = kl_divergence(sim_hours, evw_hours, bins=24, lo=0.0, hi=24.0)

    # ---- Report -----------------------------------------------------------
    out_csv = args.out or (run / f"validation_evwatts_it{args.iter}.csv")
    pd.DataFrame([{
        "run": run.name,
        "iter": args.iter,
        "n_sim_sessions": len(stats_df),
        "sim_dcfc_share": sim_dcfc_share,
        "evw_dcfc_share": evw_dcfc_share,
        "dcfc_share_gap": sim_dcfc_share - evw_dcfc_share,
        "kl_energy": kl_e,
        "kl_start_hour": kl_h,
    }]).to_csv(out_csv, index=False)

    print()
    print("[results]")
    print(f"  sim DCFC share          : {sim_dcfc_share:.4f}  ({100*sim_dcfc_share:.2f}%)")
    print(f"  EVWatts DCFC share      : {evw_dcfc_share:.4f}  ({100*evw_dcfc_share:.2f}%)")
    print(f"  DCFC gap (sim - EVW)    : {sim_dcfc_share - evw_dcfc_share:+.4f}")
    print(f"  KL(energy: sim || EVW)  : {kl_e:.4f}")
    print(f"  KL(hour:   sim || EVW)  : {kl_h:.4f}")
    print()
    print(f"[wrote] {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
