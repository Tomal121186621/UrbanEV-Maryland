#!/usr/bin/env python3
"""
validate_start_hour_v1.py

Resolve the 4-h peak-hour offset between sim and ChargePoint occupancy by
comparing session START TIMES (arrivals) instead of concurrent occupancy.

Sim occupancy = plugged-and-actively-charging (only while SoC climbs).
CP occupancy  = plug-and-leave dwell (session continues after SoC full).

Session-start comparison bypasses this semantic mismatch: it asks
"at what hour do drivers arrive/plug in?" — a clean apples-to-apples.

Deliverables (all in output/phase_R_calibration/validation/):
  start_hour_validation.csv
  start_hour_hist.pdf
"""
from __future__ import annotations
import csv
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]  # UrbanEV-Maryland/ (portable; was hardcoded Windows path)

SIM_CSV   = ROOT / "output/final_runs/baseline/ITERS/it.50/50.charging_sessions.csv"
EVW_SESS  = ROOT / "data_ext/evwatts/evwatts.public/evwatts.public.session.csv"
EVW_EVSE  = ROOT / "data_ext/evwatts/evwatts.public/evwatts.public.evse.csv"
CP_DB     = ROOT / "data_ext/ChargePoint Data Collection/chargepoint_md.db"

OUT_DIR   = ROOT / "output/phase_R_calibration/validation"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def effective_type(row: pd.Series) -> str:
    at = str(row["activity_type"]).lower()
    ct = str(row["charger_type"])
    if at.startswith("home"):
        return "home"
    if ct == "L2" and "work" in at:
        return "work"
    return ct  # "L2" / "DCFC" / "DCFC_TESLA"


# ---------------------------------------------------------------------------
# 1) Sim sessions
# ---------------------------------------------------------------------------
def load_sim() -> pd.DataFrame:
    df = pd.read_csv(SIM_CSV, sep=";")
    df["eff_type"] = df.apply(effective_type, axis=1)
    # MATSim epoch: iteration mobsim starts at t=0 -> Monday convention (sim day 1)
    # Weekday only: sim runs a single representative day; every session is a
    # weekday session by construction (no weekend in MATSim baseline).
    tsec = df["time_start_s"].astype(float).values
    df["hour"] = ((np.floor(tsec / 3600.0)) % 24).astype(int)
    return df[["session_id", "eff_type", "hour", "time_start_s"]]


# ---------------------------------------------------------------------------
# 2) EVWatts sessions filtered to MD metros
# ---------------------------------------------------------------------------
def load_evwatts() -> pd.DataFrame:
    """Return per-session {charge_level, hour} for MD metros, weekdays only."""
    evse_lvl: dict[str, str] = {}
    with EVW_EVSE.open(encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            metro = row.get("metro_area", "")
            if "Baltimore" in metro:  # per task: Baltimore-Columbia-Towson specifically
                evse_lvl[row["evse_id"]] = row.get("charge_level", "")

    hours: list[int] = []
    levels: list[str] = []
    with EVW_SESS.open(encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            lvl = evse_lvl.get(row["evse_id"])
            if lvl is None:
                continue
            ts = pd.to_datetime(row.get("start_datetime"), errors="coerce")
            if pd.isna(ts):
                continue
            if ts.weekday() >= 5:  # Sat/Sun
                continue
            hours.append(int(ts.hour))
            levels.append(lvl)
    return pd.DataFrame({"charge_level": levels, "hour": hours})


# ---------------------------------------------------------------------------
# 3) ChargePoint arrival-time proxy: transitions where in_use_ports increases
# ---------------------------------------------------------------------------
def load_cp_arrivals() -> pd.DataFrame:
    """Detect arrivals as +delta in in_use_ports per station between snapshots.
    Returns {hour, arrivals} restricted to weekday snapshots."""
    con = sqlite3.connect(str(CP_DB))
    # We do this in SQL for speed; for each station, look at consecutive
    # snapshots and sum positive deltas.
    query = """
    WITH s AS (
      SELECT station_id,
             accessed_time_utc,
             in_use_ports,
             LAG(in_use_ports) OVER (PARTITION BY station_id ORDER BY accessed_time_utc) AS prev_in_use,
             LAG(accessed_time_utc) OVER (PARTITION BY station_id ORDER BY accessed_time_utc) AS prev_t
      FROM charging_session_v2
    )
    SELECT accessed_time_utc, (in_use_ports - prev_in_use) AS delta
    FROM s
    WHERE prev_in_use IS NOT NULL AND (in_use_ports - prev_in_use) > 0
    """
    df = pd.read_sql(query, con)
    con.close()
    # UTC timestamps -> convert to America/New_York for MD local hour
    ts = pd.to_datetime(df["accessed_time_utc"], utc=True, errors="coerce")
    local = ts.dt.tz_convert("America/New_York")
    df["hour"] = local.dt.hour
    df["dow"] = local.dt.dayofweek
    df = df[df["dow"] < 5]  # weekdays
    df["arrivals"] = df["delta"].astype(int)
    return df[["hour", "arrivals"]]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def hist24(values: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
    h, _ = np.histogram(values, bins=np.arange(25), weights=weights)
    return h.astype(float)


def norm(h: np.ndarray) -> np.ndarray:
    s = h.sum()
    return h / s if s > 0 else h


def peak(h: np.ndarray) -> int:
    return int(np.argmax(h))


def ks_from_hist(h1: np.ndarray, h2: np.ndarray) -> tuple[float, float]:
    """KS 2-sample from hourly histograms via cdf comparison."""
    n1, n2 = h1.sum(), h2.sum()
    if n1 == 0 or n2 == 0:
        return float("nan"), float("nan")
    cdf1 = np.cumsum(h1) / n1
    cdf2 = np.cumsum(h2) / n2
    d = float(np.max(np.abs(cdf1 - cdf2)))
    # asymptotic 2-sample p
    en = math.sqrt(n1 * n2 / (n1 + n2))
    p = stats.kstwobign.sf((en + 0.12 + 0.11 / en) * d)
    return d, float(p)


def chi2_from_hist(h1: np.ndarray, h2: np.ndarray) -> tuple[float, float]:
    """Scale h2 to h1 total then χ².  Skip bins with expected < 5."""
    if h1.sum() == 0 or h2.sum() == 0:
        return float("nan"), float("nan")
    exp = h2 * (h1.sum() / h2.sum())
    mask = exp >= 5
    if mask.sum() < 2:
        return float("nan"), float("nan")
    chi = float(np.sum((h1[mask] - exp[mask]) ** 2 / exp[mask]))
    df = int(mask.sum() - 1)
    p = float(stats.chi2.sf(chi, df))
    return chi, p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("[1/3] Loading sim sessions...")
    sim = load_sim()
    print(f"      sim rows={len(sim):,} eff_type counts:\n{sim['eff_type'].value_counts()}")

    print("[2/3] Loading EVWatts MD (Baltimore metro, weekdays)...")
    evw = load_evwatts()
    print(f"      EVW rows={len(evw):,} charge_level counts:\n{evw['charge_level'].value_counts()}")

    print("[3/3] Loading ChargePoint arrivals (SQL LAG diff, weekdays local)...")
    cp = load_cp_arrivals()
    total_arr = int(cp["arrivals"].sum())
    print(f"      CP arrival events (weekday) total={total_arr:,}")

    # sim histograms per eff_type
    sim_l2   = hist24(sim.loc[sim["eff_type"].isin(["L2", "work", "home"]), "hour"].values)
    sim_pub_l2 = hist24(sim.loc[sim["eff_type"].isin(["L2", "work"]), "hour"].values)  # public L2 only
    sim_dcfc = hist24(sim.loc[sim["eff_type"].isin(["DCFC", "DCFC_TESLA"]), "hour"].values)
    sim_pub  = hist24(sim.loc[sim["eff_type"].isin(["L2", "work", "DCFC", "DCFC_TESLA"]), "hour"].values)

    # EVW histograms  (Level2 / DCFC labels)
    # EVWatts charge_level in this dataset uses "L2" / "DCFC" / "L1"
    evw_l2   = hist24(evw.loc[evw["charge_level"].str.contains("L2|Level2", case=False, na=False, regex=True), "hour"].values)
    evw_dcfc = hist24(evw.loc[evw["charge_level"].str.contains("DCFC", case=False, na=False), "hour"].values)
    evw_all  = evw_l2 + evw_dcfc

    # CP arrivals weighted histogram (arrivals not sessions)
    cp_h = hist24(cp["hour"].values, weights=cp["arrivals"].values.astype(float))

    rows = []
    for label, sim_h, evw_h in [
        ("L2_public",  sim_pub_l2, evw_l2),
        ("DCFC",       sim_dcfc,   evw_dcfc),
        ("all_public", sim_pub,    evw_all),
    ]:
        ks_d, ks_p = ks_from_hist(sim_h, evw_h)
        chi, chi_p = chi2_from_hist(sim_h, evw_h)
        rows.append({
            "type": label,
            "sim_n": int(sim_h.sum()),
            "evw_n": int(evw_h.sum()),
            "cp_arrivals_n": int(cp_h.sum()) if label == "all_public" else "",
            "sim_peak_hour":  peak(sim_h),
            "evw_peak_hour":  peak(evw_h),
            "cp_peak_hour":   peak(cp_h) if label == "all_public" else "",
            "peak_offset_sim_vs_evw":  peak(evw_h) - peak(sim_h),
            "peak_offset_sim_vs_cp":  (peak(cp_h) - peak(sim_h)) if label == "all_public" else "",
            "abs_peak_err_sim_vs_evw": abs(peak(evw_h) - peak(sim_h)),
            "ks_D": ks_d, "ks_p": ks_p,
            "chi2": chi, "chi2_p": chi_p,
        })

    out_csv = OUT_DIR / "start_hour_validation.csv"
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(f"[out] {out_csv}")

    # Plot
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), sharey=False)
    hours = np.arange(24)
    for ax, title, sim_h, evw_h, cp_overlay in [
        (axes[0], "L2 (public)",  sim_pub_l2, evw_l2,   None),
        (axes[1], "DCFC",         sim_dcfc,   evw_dcfc, None),
        (axes[2], "All public",   sim_pub,    evw_all,  cp_h),
    ]:
        ax.plot(hours, norm(sim_h),   label=f"Sim  (peak={peak(sim_h)}h)",  lw=2.0)
        ax.plot(hours, norm(evw_h),   label=f"EVW  (peak={peak(evw_h)}h)",  lw=2.0, ls="--")
        if cp_overlay is not None:
            ax.plot(hours, norm(cp_overlay), label=f"CP-arr(peak={peak(cp_overlay)}h)", lw=2.0, ls=":")
        ax.set_title(f"{title}: session-start hour")
        ax.set_xlabel("Hour of day (local)")
        ax.set_ylabel("Share of sessions")
        ax.set_xticks(range(0, 24, 3))
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="upper left")

    fig.suptitle("Corrected peak-hour comparison — session START (arrivals), weekdays", fontsize=11)
    fig.tight_layout()
    pdf = OUT_DIR / "start_hour_hist.pdf"
    fig.savefig(pdf, bbox_inches="tight")
    print(f"[out] {pdf}")
    print("done.")


if __name__ == "__main__":
    main()
