#!/usr/bin/env python3
"""Compare iter 40 (last innovating iter) vs iter 50 (final) on the same
validation metrics as v4. Answers: is iter 40 a better baseline than iter 50?

Reuses functions from validate_vs_chargepoint_v4.py — no augmentation, just
retargets its sim_diurnal step at iter 40 and re-runs metrics against the
same ChargePoint observed diurnal (time-independent). Prior iter 50 outputs
in output/phase_R_calibration/validation/ are untouched.

Writes:
  output/phase_R_calibration/diagnosis_v2/iter40_sim_diurnal.csv
  output/phase_R_calibration/diagnosis_v2/iter40_sim_cp_pairs.csv
  output/phase_R_calibration/diagnosis_v2/iter40_station_metrics.csv
  stdout: side-by-side comparison table.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "analysis"))

import numpy as np
import pandas as pd
import validate_vs_chargepoint_v4 as v4

ITER40_XY = REPO_ROOT / "output/final_runs/baseline/ITERS/it.40/40.charger_occupancy_absolute.xy.gz"
OUT = REPO_ROOT / "output/phase_R_calibration/diagnosis_v2"
VALID = REPO_ROOT / "output/phase_R_calibration/validation"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    print("[iter40] streaming sim occupancy...")
    sim40 = v4.sim_diurnal(ITER40_XY)
    sim40.to_csv(OUT / "iter40_sim_diurnal.csv", index=False)
    print(f"[iter40] sim chargers: {sim40.charger_id.nunique():,}")

    # Reuse CP diurnal from disk (v4 already computed it, time-independent)
    cp = pd.read_csv(VALID / "cp_diurnal.csv")
    print(f"[cp] stations: {cp.station_id.nunique():,}")

    # Spatial join to CP (identical geometry as iter 50)
    pairs40 = v4.spatial_join(sim40, v4.CP_DB)
    pairs40.to_csv(OUT / "iter40_sim_cp_pairs.csv", index=False)

    # Compute per-pair metrics
    sim_wide = v4.pivot24(sim40, "charger_id")
    cp_wide = v4.pivot24(cp, "station_id")
    m40 = v4.per_pair_metrics(pairs40, sim_wide, cp_wide)
    m40.to_csv(OUT / "iter40_station_metrics.csv", index=False)

    # Load iter 50 metrics for comparison
    m50 = pd.read_csv(VALID / "chargepoint_station_validation_v4.csv")

    print("\n" + "="*72)
    print("COMPARISON: iter 40 (last innovating) vs iter 50 (final)")
    print("="*72)

    def summarize(m: pd.DataFrame, label: str) -> dict:
        row = {
            "iter": label,
            "n_pairs": len(m),
            "median_rmse": m["rmse"].median(),
            "mean_rmse": m["rmse"].mean(),
            "median_r": m["pearson_r"].median(),
            "median_peak_err": m["peak_hour_abs_err"].median(),
            "sim_peak_hour_mode": int(m["peak_hour_sim"].mode().iat[0]),
            "obs_peak_hour_mode": int(m["peak_hour_obs"].mode().iat[0]),
        }
        return row

    tbl = pd.DataFrame([summarize(m40, "iter40"), summarize(m50, "iter50")])
    print(tbl.to_string(index=False))

    # By type
    print("\nBy sim_type (median RMSE / median r / n):")
    for t in ["L2", "DCFC"]:
        s40 = m40[m40["sim_type"] == t]
        s50 = m50[m50["sim_type"] == t]
        print(f"  {t:5s}  iter40: RMSE={s40['rmse'].median():.3f}  r={s40['pearson_r'].median():.3f}  n={len(s40)}")
        print(f"         iter50: RMSE={s50['rmse'].median():.3f}  r={s50['pearson_r'].median():.3f}  n={len(s50)}")

    # Filter sparse stations (mean_obs > 0.05 AND mean_sim > 0.02)
    print("\nWith sparse-station filter (mean_obs > 0.05 AND mean_sim > 0.02):")
    for m, label in [(m40, "iter40"), (m50, "iter50")]:
        f = m[(m["mean_obs_occupancy"] > 0.05) & (m["mean_sim_occupancy"] > 0.02)]
        print(f"  {label}  n={len(f):<4d}  median RMSE={f['rmse'].median():.3f}  median r={f['pearson_r'].median():.3f}  median peak_err={f['peak_hour_abs_err'].median():.1f}h")

    # Also: iter 40 vs iter 50 per-type SHARES from charging_sessions
    print("\nPer-type shares from charging_sessions.csv (from diagnosis_v2 D):")
    d = pd.read_csv(OUT / "D_shares_by_iter.csv") if (OUT / "D_shares_by_iter.csv").exists() else None
    if d is not None:
        print(d.tail(2).to_string(index=False))

    tbl.to_csv(OUT / "iter40_vs_iter50_comparison.csv", index=False)
    print(f"\n[done] wrote {OUT / 'iter40_vs_iter50_comparison.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
