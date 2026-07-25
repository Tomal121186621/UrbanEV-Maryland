#!/usr/bin/env python3
"""
validate_chargepoint_aggregate.py — AGGREGATE ChargePoint validation (robust to the
station-level noise that made per-station r low). Compares statewide public-charging
occupancy between the simulation and 1.76M ChargePoint occupancy polls:
  - diurnal occupancy shape (24-h profile, all public stations pooled) -> Pearson r, peak hr
  - weekday vs weekend shape
  - utilization level (mean occupied ports / total ports)
Figures + metrics -> output/runs_2026/validation/.
"""
import sqlite3, gzip
from pathlib import Path
import numpy as np, pandas as pd
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data_ext/ChargePoint Data Collection/chargepoint_md.db"
SIM = ROOT / "scenarios/maryland/output/runs_2026/baseline/ITERS/it.50/50.charger_occupancy_absolute.xy.gz"
OUT = ROOT / "scenarios/maryland/output/runs_2026/validation"
CP, SM = pf.BLUE, pf.ORANGE


def norm(v):
    v = np.asarray(v, float); return v / v.sum()


def main():
    # ---- ChargePoint: occupancy polls -> ET hour-of-day, weekday/weekend ----
    c = sqlite3.connect(DB)
    cp = pd.read_sql("SELECT station_id,accessed_time_utc,in_use_ports,available_ports "
                     "FROM charging_session_v2", c)
    t = pd.to_datetime(cp.accessed_time_utc, utc=True, format="mixed").dt.tz_convert("America/New_York")
    cp["hour"] = t.dt.hour; cp["wknd"] = t.dt.dayofweek >= 5
    cp["ports"] = cp.in_use_ports + cp.available_ports + cp.other_ports if "other_ports" in cp else cp.in_use_ports + cp.available_ports
    cp_diur = cp.groupby("hour").in_use_ports.mean().reindex(range(24), fill_value=0)
    cp_wd = cp[~cp.wknd].groupby("hour").in_use_ports.mean().reindex(range(24), fill_value=0)
    cp_we = cp[cp.wknd].groupby("hour").in_use_ports.mean().reindex(range(24), fill_value=0)
    cp_util = float((cp.in_use_ports.sum()) / (cp.in_use_ports + cp.available_ports).sum())

    # ---- Sim: public chargers only (exclude home shh_/agent ids), plugged by hour ----
    d = pd.read_csv(SIM, sep="\t")
    pub = d[d.id.str.contains("_MD_", na=False)].copy()          # l1/l2/dcfc_MD_* = AFDC public
    pub["hour"] = (pub.time.astype(float) % 86400 / 3600).astype(int).clip(0, 23)
    sim_diur = pub.groupby("hour").plugged.mean().reindex(range(24), fill_value=0)
    sim_util = float(pub.plugged.sum() / pub.plugs.sum())

    # ---- compare (normalized shapes) ----
    r = np.corrcoef(norm(cp_diur), norm(sim_diur))[0, 1]
    tvd = 0.5 * np.abs(norm(cp_diur) - norm(sim_diur)).sum()
    peak_cp, peak_sim = int(np.argmax(cp_diur)), int(np.argmax(sim_diur))
    print(f"[aggregate ChargePoint] diurnal shape r={r:.3f}  TVD={tvd:.3f}  "
          f"peak CP={peak_cp}h sim={peak_sim}h | util CP={cp_util:.1%} sim={sim_util:.1%}")

    # ---- Fig: normalized diurnal overlay ----
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.plot(range(24), norm(cp_diur), "-o", color=CP, lw=2, ms=4, label=f"ChargePoint (observed)")
    ax.plot(range(24), norm(sim_diur), "-s", color=SM, lw=2, ms=4, label=f"Simulation")
    ax.set(xlabel="hour of day (ET)", ylabel="share of daily public occupancy",
           title=f"Public-charging diurnal profile  (r={r:.2f}, peak CP {peak_cp}h / sim {peak_sim}h)",
           xticks=range(0, 24, 3))
    ax.legend(); fig.tight_layout()
    fig.savefig(OUT / "cp_aggregate_diurnal.pdf"); fig.savefig(OUT / "cp_aggregate_diurnal.png"); plt.close(fig)

    # ---- Fig: weekday vs weekend (CP) with sim overlay ----
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.plot(range(24), norm(cp_wd), color=CP, lw=2, label="ChargePoint weekday")
    ax.plot(range(24), norm(cp_we), color=CP, lw=1.4, ls="--", label="ChargePoint weekend")
    ax.plot(range(24), norm(sim_diur), color=SM, lw=2, label="Simulation")
    ax.set(xlabel="hour of day (ET)", ylabel="share of daily occupancy",
           title="Public occupancy: weekday vs weekend", xticks=range(0, 24, 3))
    ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig(OUT / "cp_weekday_weekend.pdf"); fig.savefig(OUT / "cp_weekday_weekend.png"); plt.close(fig)

    pd.DataFrame([{"metric": "diurnal_shape_r", "value": round(r, 3)},
                  {"metric": "diurnal_TVD", "value": round(tvd, 3)},
                  {"metric": "peak_hour_CP", "value": peak_cp},
                  {"metric": "peak_hour_sim", "value": peak_sim},
                  {"metric": "utilization_CP", "value": round(cp_util, 3)},
                  {"metric": "utilization_sim", "value": round(sim_util, 3)}]
                 ).to_csv(OUT / "cp_aggregate_metrics.csv", index=False)
    print(f"[done] 2 figures + metrics -> {OUT}")


if __name__ == "__main__":
    main()
